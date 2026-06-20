"""
HeyDoc API — auth + the RAG pipeline (ingestion / imaging / retrieval / advanced_rag)
=======================================================================================
Auth generates the same kind of id (`{role}_xxxxxxxx`) that ingestion.py expects as
`patient_id`, so a signed-up patient's id is passed straight through to ChromaDB.

RAG models (docTR, bge-large embedder, reranker, Gemini client) are heavy, so they're
loaded lazily on the first /documents/upload or /chat call rather than at startup —
that first call will be slow (~30s-2min depending on your machine), every call after
is fast.

Run with: uvicorn server:app --reload --port 8000
Requires a .env file with GEMINI_API_KEY set.
"""
import base64
import datetime
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import qrcode

# ingestion/retrieval/advanced_rag/imaging print Unicode box-drawing characters
# (─, •, ⚠) — Windows' default console codepage (cp1252) can't encode them and
# crashes mid-pipeline. Force UTF-8 on stdout/stderr before anything else runs.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

import ingestion
import retrieval
import advanced_rag
import imaging
import admission as admission_engine

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "heydoc.db")
VALID_ROLES = {"patient", "doctor", "tpa", "lab", "admin"}

# Default semantic-type badge for a document, keyed by doc_type — mirrors
# ingestion._DOC_TYPE_TO_SEMANTIC, duplicated here since it's only used for
# the document-list UI badge, not for retrieval.
DOC_TYPE_DEFAULT_SEMANTIC = {
    "prescription": "medication_history",
    "discharge_summary": "patient_information",
    "lab_report": "lab_reports",
    "biopsy_report": "surgical_history",
    "imaging_report": "lab_reports",
    "operative_notes": "surgical_history",
    "insurance": "patient_information",
    "imaging_scan": "lab_reports",
    "identity_proof": "patient_information",
    "admission_intake": "patient_information",
    "unknown": "patient_information",
}

SCAN_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}

# Rough per-visit-type consultation length, used for queue ETA until there's
# enough real started_at/completed_at history to compute an actual average.
AVG_CONSULT_MINUTES = {"follow_up": 10, "new": 20, "admission": 30}
CHECKIN_WINDOW_MINUTES = 30  # check-in opens this many minutes before the slot

app = FastAPI(title="HeyDoc API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                dept TEXT,
                room TEXT,
                hospital TEXT,
                timings TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                uploaded_by TEXT NOT NULL,
                file_name TEXT NOT NULL,
                doc_type TEXT,
                semantic_type TEXT,
                pipeline TEXT,
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                doctor_id TEXT NOT NULL,
                time TEXT NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # sqlite has no "ADD COLUMN IF NOT EXISTS" — added after the table already
        # existed in earlier versions of this app, so guard each with try/except.
        for col in ("checked_in_at", "started_at", "completed_at"):
            try:
                conn.execute(f"ALTER TABLE appointments ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
        try:
            # Doctor-controlled "running early/late" offset for today's queue —
            # only meaningful for role='doctor' but harmless on other rows.
            conn.execute("ALTER TABLE users ADD COLUMN queue_drift_minutes INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        for col, coltype in (("admission_id", "TEXT"), ("slot", "TEXT")):
            try:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admissions (
                id TEXT PRIMARY KEY,
                appointment_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                doctor_id TEXT NOT NULL,
                admission_date TEXT,
                admission_reason TEXT,
                payment_path TEXT NOT NULL DEFAULT 'self_pay',
                is_corporate INTEGER NOT NULL DEFAULT 0,
                estimated_cost INTEGER,
                preauth_json TEXT,
                status TEXT NOT NULL DEFAULT 'in_progress',
                token TEXT UNIQUE,
                token_redeemed INTEGER NOT NULL DEFAULT 0,
                ward TEXT,
                bed_number TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admission_checklist_items (
                id TEXT PRIMARY KEY,
                admission_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                tier INTEGER NOT NULL,
                status TEXT NOT NULL,
                source_document_id TEXT,
                explanation TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(admission_id, item_key)
            )
            """
        )


init_db()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return digest.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


def make_user_id(role: str) -> str:
    return f"{role}_{uuid.uuid4().hex[:8]}"


def user_public(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "name": row["name"],
        "email": row["email"],
        "dept": row["dept"],
        "room": row["room"],
        "hospital": row["hospital"],
        "timings": row["timings"],
    }


class SignupRequest(BaseModel):
    role: str
    name: str
    email: EmailStr
    password: str
    dept: str | None = None
    room: str | None = None
    hospital: str | None = None
    timings: str | None = None


class SigninRequest(BaseModel):
    email: EmailStr
    password: str


@app.post("/signup")
def signup(req: SignupRequest):
    role = req.role.strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(VALID_ROLES)}")
    if not req.name.strip():
        raise HTTPException(400, "name is required")
    if len(req.password) < 6:
        raise HTTPException(400, "password must be at least 6 characters")

    password_hash, salt = hash_password(req.password)
    user_id = make_user_id(role)

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (req.email.lower(),)
        ).fetchone()
        if existing:
            raise HTTPException(409, "an account with this email already exists")

        conn.execute(
            """
            INSERT INTO users (id, role, name, email, password_hash, password_salt, dept, room, hospital, timings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                role,
                req.name.strip(),
                req.email.lower(),
                password_hash,
                salt,
                req.dept,
                req.room,
                req.hospital,
                req.timings,
            ),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    return user_public(row)


@app.post("/signin")
def signin(req: SigninRequest):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (req.email.lower(),)
        ).fetchone()

    if not row or not verify_password(req.password, row["password_salt"], row["password_hash"]):
        raise HTTPException(401, "invalid email or password")

    return user_public(row)


@app.get("/patients")
def list_patients(doctor_id: str | None = None, hospital: str | None = None):
    """
    Patients a caller is allowed to see/act on:
      - doctor_id given  -> patients with an accepted-or-later appointment with that doctor
      - hospital given   -> (tpa/lab/admin) patients with an accepted-or-later
                             appointment with ANY doctor at that hospital
      - neither given    -> everyone (used internally; the frontend always scopes
                             this for doctor/tpa/lab/admin callers)

    "Accepted-or-later" = not 'pending' (never decided) and not 'declined'
    (explicitly rejected) — this covers accepted/checked_in/in_consultation/
    completed/no_show, i.e. once a doctor has taken on a patient, access
    persists through and after the consultation, not just while still 'accepted'.
    """
    with get_db() as conn:
        if doctor_id:
            rows = conn.execute(
                """
                SELECT DISTINCT u.id, u.name FROM users u
                JOIN appointments a ON a.patient_id = u.id
                WHERE a.doctor_id = ? AND a.status NOT IN ('pending', 'declined')
                ORDER BY u.name
                """,
                (doctor_id,),
            ).fetchall()
        elif hospital:
            rows = conn.execute(
                """
                SELECT DISTINCT p.id, p.name FROM users p
                JOIN appointments a ON a.patient_id = p.id
                JOIN users d ON d.id = a.doctor_id
                WHERE a.status NOT IN ('pending', 'declined') AND LOWER(d.hospital) = LOWER(?)
                ORDER BY p.name
                """,
                (hospital,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name FROM users WHERE role = 'patient' ORDER BY name"
            ).fetchall()
    return [dict(r) for r in rows]


def authorize_patient_access(
    conn: sqlite3.Connection,
    role: str | None,
    requester_id: str,
    requester_hospital: str | None,
    patient_id: str,
) -> bool:
    """
    Business rule: a doctor may only access a patient's vault/uploads once they
    have accepted an appointment with that patient — and access persists through
    the rest of the queue lifecycle (checked_in/in_consultation/completed/no_show),
    not just while still 'accepted'. TPA/lab/admin (insurance desk, diagnostics,
    front desk/helpdesk) may only access a patient if that patient has an
    accepted-or-later appointment with a doctor at the same hospital as their
    own account. Patients always have access to their own records.
    """
    if requester_id == patient_id:
        return True
    if role == "doctor":
        return conn.execute(
            "SELECT 1 FROM appointments WHERE doctor_id = ? AND patient_id = ? AND status NOT IN ('pending', 'declined') LIMIT 1",
            (requester_id, patient_id),
        ).fetchone() is not None
    if role in ("tpa", "lab", "admin"):
        if not requester_hospital:
            return False
        return conn.execute(
            """
            SELECT 1 FROM appointments a JOIN users d ON d.id = a.doctor_id
            WHERE a.patient_id = ? AND a.status NOT IN ('pending', 'declined') AND LOWER(d.hospital) = LOWER(?)
            LIMIT 1
            """,
            (patient_id, requester_hospital),
        ).fetchone() is not None
    return True


@app.get("/doctors")
def list_doctors():
    """All signed-up doctors with their availability — lets a patient pick one to book."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, dept, room, hospital, timings FROM users WHERE role = 'doctor' ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


class DriftAdjustment(BaseModel):
    delta_minutes: int


@app.get("/doctors/{doctor_id}/drift")
def get_doctor_drift(doctor_id: str):
    """How far ahead/behind schedule this doctor says they're running right now."""
    with get_db() as conn:
        row = conn.execute("SELECT queue_drift_minutes FROM users WHERE id = ?", (doctor_id,)).fetchone()
    return {"drift_minutes": row["queue_drift_minutes"] if row else 0}


@app.post("/doctors/{doctor_id}/drift")
def adjust_doctor_drift(doctor_id: str, req: DriftAdjustment):
    """
    Doctor nudges their running-early/late offset by +/-5 (etc). This shifts the
    estimated call time for every one of their waiting patients at once — the
    actual scheduled slot times never change, just this offset applied on top.
    """
    with get_db() as conn:
        row = conn.execute("SELECT queue_drift_minutes FROM users WHERE id = ?", (doctor_id,)).fetchone()
        if not row:
            return {"drift_minutes": 0}  # demo account with no real row — nothing to persist
        new_value = row["queue_drift_minutes"] + req.delta_minutes
        conn.execute("UPDATE users SET queue_drift_minutes = ? WHERE id = ?", (new_value, doctor_id))
    return {"drift_minutes": new_value}


# ── Appointments ────────────────────────────────────────────────────────────

class AppointmentRequest(BaseModel):
    patient_id: str
    doctor_id: str
    time: str
    type: str


class AppointmentStatusUpdate(BaseModel):
    status: str


def appointment_public(row: sqlite3.Row, conn: sqlite3.Connection) -> dict:
    patient = conn.execute("SELECT name FROM users WHERE id = ?", (row["patient_id"],)).fetchone()
    doctor = conn.execute(
        "SELECT name, dept, room, hospital FROM users WHERE id = ?", (row["doctor_id"],)
    ).fetchone()
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "patient_name": patient["name"] if patient else row["patient_id"],
        "doctor_id": row["doctor_id"],
        "doctor_name": doctor["name"] if doctor else row["doctor_id"],
        "dept": doctor["dept"] if doctor else None,
        "room": doctor["room"] if doctor else None,
        "hospital": doctor["hospital"] if doctor else None,
        "time": row["time"],
        "type": row["type"],
        "status": row["status"],
        "checked_in_at": row["checked_in_at"],
    }


@app.post("/appointments")
def create_appointment(req: AppointmentRequest):
    # No FK enforcement on patient_id/doctor_id, same as /documents/upload — the
    # frontend's doctor/patient pickers can include the built-in demo accounts
    # (quick-sign-in), which have no real row in `users` but are otherwise
    # fully functional sessions. appointment_public() already falls back to
    # the raw id if the row doesn't exist.
    appt_id = uuid.uuid4().hex[:12]
    with get_db() as conn:
        conn.execute(
            "INSERT INTO appointments (id, patient_id, doctor_id, time, type, status) VALUES (?, ?, ?, ?, ?, 'pending')",
            (appt_id, req.patient_id, req.doctor_id, req.time, req.type),
        )
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        return appointment_public(row, conn)


@app.get("/appointments")
def list_appointments(patient_id: str | None = None, doctor_id: str | None = None):
    with get_db() as conn:
        if patient_id:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE patient_id = ? ORDER BY time", (patient_id,)
            ).fetchall()
        elif doctor_id:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE doctor_id = ? ORDER BY time", (doctor_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM appointments ORDER BY time").fetchall()
        return [appointment_public(r, conn) for r in rows]


@app.post("/appointments/{appointment_id}/status")
def update_appointment_status(appointment_id: str, req: AppointmentStatusUpdate):
    # 'checked_in' is deliberately excluded here — it has its own endpoint
    # below that enforces the check-in window.
    valid = {"pending", "accepted", "declined", "in_consultation", "completed", "no_show"}
    if req.status not in valid:
        raise HTTPException(400, f"status must be one of {sorted(valid)}")
    with get_db() as conn:
        if not conn.execute("SELECT id FROM appointments WHERE id = ?", (appointment_id,)).fetchone():
            raise HTTPException(404, "appointment not found")
        now = datetime.datetime.now().isoformat()
        if req.status == "in_consultation":
            conn.execute("UPDATE appointments SET status = ?, started_at = ? WHERE id = ?", (req.status, now, appointment_id))
        elif req.status == "completed":
            conn.execute("UPDATE appointments SET status = ?, completed_at = ? WHERE id = ?", (req.status, now, appointment_id))
        else:
            conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (req.status, appointment_id))
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return appointment_public(row, conn)


@app.post("/appointments/{appointment_id}/check-in")
def check_in_appointment(appointment_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "appointment not found")
        if row["status"] != "accepted":
            raise HTTPException(400, f"can only check in from 'accepted' status (current: {row['status']})")

        # Appointment times and datetime.now() are both naive local-clock values
        # (the frontend sends `${date}T${time}:00` straight from the patient's
        # wall clock, no timezone conversion anywhere) — directly comparable.
        # NOTE: this was originally written against utcnow(), which silently
        # broke the check-in window by the server's UTC offset (e.g. ~5.5h in
        # IST) — utcnow() must never be mixed with these naive-local values.
        appt_time = datetime.datetime.fromisoformat(row["time"])
        mins_until = (appt_time - datetime.datetime.now()).total_seconds() / 60
        if mins_until > CHECKIN_WINDOW_MINUTES:
            raise HTTPException(400, f"check-in opens {CHECKIN_WINDOW_MINUTES} minutes before your appointment")

        now = datetime.datetime.now().isoformat()
        conn.execute(
            "UPDATE appointments SET status = 'checked_in', checked_in_at = ? WHERE id = ?",
            (now, appointment_id),
        )
        updated = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return appointment_public(updated, conn)


@app.get("/appointments/{appointment_id}/queue-position")
def get_queue_position(appointment_id: str):
    with get_db() as conn:
        appt = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        if not appt:
            raise HTTPException(404, "appointment not found")

        doctor = conn.execute("SELECT queue_drift_minutes FROM users WHERE id = ?", (appt["doctor_id"],)).fetchone()
        drift_minutes = doctor["queue_drift_minutes"] if doctor else 0

        if appt["status"] not in ("checked_in", "in_consultation"):
            return {
                "position": None, "ahead_count": None, "status": appt["status"],
                "estimated_wait_minutes": None, "is_current": False,
                "estimated_call_time": None, "drift_minutes": drift_minutes,
            }

        appt_day = appt["time"][:10]  # YYYY-MM-DD prefix
        queue = conn.execute(
            """
            SELECT * FROM appointments
            WHERE doctor_id = ? AND status IN ('checked_in', 'in_consultation')
              AND substr(time, 1, 10) = ?
            ORDER BY time ASC, COALESCE(checked_in_at, '') ASC
            """,
            (appt["doctor_id"], appt_day),
        ).fetchall()

        ids_in_order = [r["id"] for r in queue]
        idx = ids_in_order.index(appointment_id)
        ahead = queue[:idx]
        ahead_count = len(ahead)
        estimated_wait_minutes = sum(AVG_CONSULT_MINUTES.get(r["type"], 15) for r in ahead)

        # The countdown patients see targets the *scheduled* slot time shifted by
        # the doctor's manual running-early/late offset — not an auto-computed
        # estimate. The doctor is the one who knows whether they're behind today.
        scheduled = datetime.datetime.fromisoformat(appt["time"])
        estimated_call_time = scheduled + datetime.timedelta(minutes=drift_minutes)

        # "You're next" notification is handled client-side (app.js maybeNotifyNext) —
        # the browser Notification API + in-app banner, no server-side trigger needed.

        return {
            "position": idx + 1,
            "ahead_count": ahead_count,
            "status": appt["status"],
            "estimated_wait_minutes": estimated_wait_minutes,
            "is_current": appt["status"] == "in_consultation",
            "estimated_call_time": estimated_call_time.isoformat(),
            "drift_minutes": drift_minutes,
        }


# ── Admission (pre-admission verification, payment, token) ────────────────────

def _token_qr_data_uri(token: str) -> str:
    """
    Generate the token's QR code server-side (the well-tested `qrcode` library,
    not a hand-rolled encoder, not a third-party QR API) and hand it to the
    frontend as a ready-to-use data URI — no client-side encoding at all.
    """
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(token)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def admission_public(row: sqlite3.Row, conn: sqlite3.Connection) -> dict:
    patient = conn.execute("SELECT name FROM users WHERE id = ?", (row["patient_id"],)).fetchone()
    doctor = conn.execute("SELECT name, dept, room, hospital FROM users WHERE id = ?", (row["doctor_id"],)).fetchone()
    items = conn.execute(
        "SELECT * FROM admission_checklist_items WHERE admission_id = ? ORDER BY item_key", (row["id"],)
    ).fetchall()
    return {
        "id": row["id"],
        "appointment_id": row["appointment_id"],
        "patient_id": row["patient_id"],
        "patient_name": patient["name"] if patient else row["patient_id"],
        "doctor_id": row["doctor_id"],
        "doctor_name": doctor["name"] if doctor else row["doctor_id"],
        "dept": doctor["dept"] if doctor else None,
        "hospital": doctor["hospital"] if doctor else None,
        "admission_date": row["admission_date"],
        "admission_reason": row["admission_reason"],
        "payment_path": row["payment_path"],
        "is_corporate": bool(row["is_corporate"]),
        "estimated_cost": row["estimated_cost"],
        "preauth": json.loads(row["preauth_json"]) if row["preauth_json"] else {},
        "status": row["status"],
        "token": row["token"],
        "qr_data_uri": _token_qr_data_uri(row["token"]) if row["token"] else None,
        "token_redeemed": bool(row["token_redeemed"]),
        "ward": row["ward"],
        "bed_number": row["bed_number"],
        "checklist": [
            {
                "item_key": it["item_key"],
                "tier": it["tier"],
                "status": it["status"],
                "source_document_id": it["source_document_id"],
                "explanation": it["explanation"],
            }
            for it in items
        ],
    }


def _build_admission_documents(conn: sqlite3.Connection, collection, admission_id: str) -> list[dict]:
    """Re-assemble each admission document's extracted text/diagnosis from
    ChromaDB (already stored there by the normal ingestion pipeline) — no
    separate text storage needed, just look it back up by patient_id+file_name."""
    # Newest first per slot — a "Replace file" re-upload must take precedence
    # over whatever was there before, not silently lose to it.
    rows = conn.execute(
        "SELECT * FROM documents WHERE admission_id = ? ORDER BY uploaded_at DESC", (admission_id,)
    ).fetchall()
    out = []
    for r in rows:
        res = collection.get(
            where={"$and": [{"patient_id": r["patient_id"]}, {"file_name": r["file_name"]}]},
            include=["documents", "metadatas"],
        )
        texts = res.get("documents") or []
        metas = res.get("metadatas") or []
        diagnosis = next((m.get("diagnosis") for m in metas if m.get("diagnosis")), None)
        out.append({
            "id": r["id"],
            "doc_type": r["doc_type"],
            "slot": r["slot"],
            "text": "\n".join(texts),
            "diagnosis": diagnosis,
        })
    return out


def _run_admission_verification(admission_id: str) -> list[dict]:
    models, _ = get_rag_models()
    with get_db() as conn:
        adm_row = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        if not adm_row:
            raise HTTPException(404, "admission not found")

        documents = _build_admission_documents(conn, models["collection"], admission_id)
        patient = conn.execute("SELECT name FROM users WHERE id = ?", (adm_row["patient_id"],)).fetchone()
        admission_dict = {
            "payment_path": adm_row["payment_path"],
            "is_corporate": bool(adm_row["is_corporate"]),
            "estimated_cost": adm_row["estimated_cost"],
            "admission_reason": adm_row["admission_reason"],
            "preauth": json.loads(adm_row["preauth_json"]) if adm_row["preauth_json"] else {},
            "patient_name": patient["name"] if patient else None,
        }
        results = admission_engine.verify_admission(admission_dict, documents, models)

        conn.execute("DELETE FROM admission_checklist_items WHERE admission_id = ?", (admission_id,))
        now = datetime.datetime.now().isoformat()
        for r in results:
            conn.execute(
                """
                INSERT INTO admission_checklist_items
                    (id, admission_id, item_key, tier, status, source_document_id, explanation, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (f"{admission_id}:{r.item_key}", admission_id, r.item_key, r.tier, r.status,
                 r.source_document_id, r.explanation, now),
            )

        # Never regress a status that's already past payment just because
        # verification re-ran (e.g. a late re-upload after the token was issued).
        if adm_row["status"] in ("in_progress", "ready_for_payment"):
            all_verified = bool(results) and all(r.status == "verified" for r in results)
            conn.execute(
                "UPDATE admissions SET status = ? WHERE id = ?",
                ("ready_for_payment" if all_verified else "in_progress", admission_id),
            )

        return [
            {"item_key": r.item_key, "tier": r.tier, "status": r.status,
             "source_document_id": r.source_document_id, "explanation": r.explanation}
            for r in results
        ]


class AdmissionCreateRequest(BaseModel):
    appointment_id: str


@app.post("/admissions")
def create_admission(req: AdmissionCreateRequest):
    with get_db() as conn:
        appt = conn.execute("SELECT * FROM appointments WHERE id = ?", (req.appointment_id,)).fetchone()
        if not appt:
            raise HTTPException(404, "appointment not found")
        existing = conn.execute(
            "SELECT * FROM admissions WHERE appointment_id = ?", (req.appointment_id,)
        ).fetchone()
        if existing:
            return admission_public(existing, conn)

        admission_id = uuid.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO admissions (id, appointment_id, patient_id, doctor_id, admission_date) VALUES (?, ?, ?, ?, ?)",
            (admission_id, req.appointment_id, appt["patient_id"], appt["doctor_id"], appt["time"][:10]),
        )

    # Populate the checklist immediately (self_pay defaults to identity+medical_doc,
    # both 'missing' with nothing uploaded yet) so the patient sees requirements
    # right away instead of an empty list. Runs in its own connection — the INSERT
    # above must be committed first (the outer `with` block already closed).
    _run_admission_verification(admission_id)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        return admission_public(row, conn)


@app.get("/admissions/{admission_id}")
def get_admission(admission_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        if not row:
            raise HTTPException(404, "admission not found")
        return admission_public(row, conn)


@app.get("/admissions")
def list_admissions(appointment_id: str | None = None, status: str | None = None, hospital: str | None = None):
    with get_db() as conn:
        if appointment_id:
            row = conn.execute("SELECT * FROM admissions WHERE appointment_id = ?", (appointment_id,)).fetchone()
            return admission_public(row, conn) if row else None
        if status == "needs_review" and hospital:
            rows = conn.execute(
                """
                SELECT i.id as item_id, i.item_key, i.tier, i.status, i.source_document_id, i.explanation,
                       a.id as admission_id, a.patient_id, a.doctor_id
                FROM admission_checklist_items i
                JOIN admissions a ON a.id = i.admission_id
                JOIN users d ON d.id = a.doctor_id
                WHERE i.status = 'needs_review' AND LOWER(d.hospital) = LOWER(?)
                ORDER BY i.updated_at
                """,
                (hospital,),
            ).fetchall()
            out = []
            for r in rows:
                patient = conn.execute("SELECT name FROM users WHERE id = ?", (r["patient_id"],)).fetchone()
                out.append({
                    "item_id": r["item_id"], "item_key": r["item_key"], "tier": r["tier"],
                    "status": r["status"], "source_document_id": r["source_document_id"],
                    "explanation": r["explanation"], "admission_id": r["admission_id"],
                    "patient_id": r["patient_id"], "patient_name": patient["name"] if patient else r["patient_id"],
                })
            return out
        if hospital:
            # Real, hospital-scoped admissions for the front desk's "Today's
            # arrivals" / intake views — paid (confirmed/redeemed) by default
            # since that's the point where the front desk actually needs to
            # act on a patient; pass an explicit status to narrow further.
            query = """
                SELECT a.* FROM admissions a
                JOIN users d ON d.id = a.doctor_id
                WHERE LOWER(d.hospital) = LOWER(?)
            """
            params = [hospital]
            if status:
                query += " AND a.status = ?"
                params.append(status)
            else:
                query += " AND a.status IN ('confirmed', 'redeemed')"
            query += " ORDER BY a.admission_date"
            rows = conn.execute(query, params).fetchall()
            return [admission_public(r, conn) for r in rows]
        raise HTTPException(400, "pass appointment_id, status=needs_review&hospital=, or hospital=")


class AdmissionUpdateRequest(BaseModel):
    admission_date: str | None = None
    admission_reason: str | None = None
    payment_path: str | None = None
    is_corporate: bool | None = None
    estimated_cost: int | None = None
    preauth: dict | None = None


@app.put("/admissions/{admission_id}")
def update_admission(admission_id: str, req: AdmissionUpdateRequest):
    with get_db() as conn:
        if not conn.execute("SELECT id FROM admissions WHERE id = ?", (admission_id,)).fetchone():
            raise HTTPException(404, "admission not found")
        fields, params = [], []
        if req.admission_date is not None:
            fields.append("admission_date = ?"); params.append(req.admission_date)
        if req.admission_reason is not None:
            fields.append("admission_reason = ?"); params.append(req.admission_reason)
        if req.payment_path is not None:
            if req.payment_path not in ("self_pay", "insurance"):
                raise HTTPException(400, "payment_path must be 'self_pay' or 'insurance'")
            fields.append("payment_path = ?"); params.append(req.payment_path)
        if req.is_corporate is not None:
            fields.append("is_corporate = ?"); params.append(int(req.is_corporate))
        if req.estimated_cost is not None:
            fields.append("estimated_cost = ?"); params.append(req.estimated_cost)
        if req.preauth is not None:
            fields.append("preauth_json = ?"); params.append(json.dumps(req.preauth))
        if fields:
            params.append(admission_id)
            conn.execute(f"UPDATE admissions SET {', '.join(fields)} WHERE id = ?", params)

    _run_admission_verification(admission_id)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        return admission_public(row, conn)


@app.post("/admissions/{admission_id}/documents")
async def upload_admission_document(
    admission_id: str,
    slot: str = Form(...),
    file: UploadFile = File(...),
):
    with get_db() as conn:
        adm = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        if not adm:
            raise HTTPException(404, "admission not found")
    patient_id = adm["patient_id"]

    models, imaging_models = get_rag_models()
    dest_dir = ingestion.UPLOAD_DIR / patient_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file.filename
    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    # Any image extension goes through Gemini Vision, not just filenames that
    # happen to mention a modality (e.g. "IMG_2384.jpg", WhatsApp exports) --
    # detect_modality() only picks which prompt to use; imaging.py already
    # has a sensible generic-description fallback for "unknown_scan".
    is_scan_image = dest_path.suffix.lower() in SCAN_IMAGE_EXTS
    if is_scan_image:
        result = imaging.ingest_scan(patient_id, dest_path, models, imaging_models)
        pipeline = "imaging"
        doc_type = "imaging_scan"
    else:
        result = ingestion.ingest_document(patient_id, dest_path, models)
        pipeline = "ingestion"
        doc_type = result.get("doc_type", "unknown")

    if result.get("status") != "ok":
        raise HTTPException(400, result.get("reason", "ingestion failed"))

    # Fallback UI label only — the real classifier's verdict (incl. "unknown")
    # is still what Tier 1 checks against; this doesn't change chunk metadata.
    display_doc_type = "admission_intake" if doc_type == "unknown" else doc_type
    semantic_type = DOC_TYPE_DEFAULT_SEMANTIC.get(display_doc_type, "patient_information")

    doc_id = uuid.uuid4().hex[:12]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO documents (id, patient_id, uploaded_by, file_name, doc_type, semantic_type, pipeline, admission_id, slot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, patient_id, patient_id, dest_path.name, display_doc_type, semantic_type, pipeline, admission_id, slot),
        )

    checklist = _run_admission_verification(admission_id)
    return {"document": {"id": doc_id, "doc_type": display_doc_type, "slot": slot}, "checklist": checklist}


@app.post("/admissions/{admission_id}/payment")
def pay_admission(admission_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        if not row:
            raise HTTPException(404, "admission not found")
        items = conn.execute(
            "SELECT status FROM admission_checklist_items WHERE admission_id = ?", (admission_id,)
        ).fetchall()
        if not items or any(it["status"] != "verified" for it in items):
            raise HTTPException(400, "every checklist item must be verified before payment")

        existing_tokens = {r["token"] for r in conn.execute("SELECT token FROM admissions WHERE token IS NOT NULL")}
        token = admission_engine.generate_token(existing_tokens)
        conn.execute(
            "UPDATE admissions SET status = 'confirmed', token = ? WHERE id = ?",
            (token, admission_id),
        )
        row = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        return admission_public(row, conn)


class ChecklistResolveRequest(BaseModel):
    status: str  # 'verified' | 'missing'
    note: str | None = None


@app.post("/admissions/checklist-items/{item_id}/resolve")
def resolve_checklist_item(item_id: str, req: ChecklistResolveRequest):
    if req.status not in ("verified", "missing"):
        raise HTTPException(400, "status must be 'verified' or 'missing'")
    with get_db() as conn:
        item = conn.execute("SELECT * FROM admission_checklist_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            raise HTTPException(404, "checklist item not found")
        default_note = (
            "Verified by hospital admin" if req.status == "verified"
            else "There seems to be a problem with this document — please re-upload it."
        )
        conn.execute(
            "UPDATE admission_checklist_items SET status = ?, explanation = ? WHERE id = ?",
            (req.status, req.note or default_note, item_id),
        )
        admission_id = item["admission_id"]
        adm_row = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        if adm_row["status"] in ("in_progress", "ready_for_payment"):
            remaining = conn.execute(
                "SELECT status FROM admission_checklist_items WHERE admission_id = ?", (admission_id,)
            ).fetchall()
            all_verified = bool(remaining) and all(r["status"] == "verified" for r in remaining)
            conn.execute(
                "UPDATE admissions SET status = ? WHERE id = ?",
                ("ready_for_payment" if all_verified else "in_progress", admission_id),
            )
        row = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        return admission_public(row, conn)


class RedeemRequest(BaseModel):
    token: str
    ward: str
    bed_number: str


@app.post("/admissions/redeem")
def redeem_token(req: RedeemRequest):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM admissions WHERE token = ?", (req.token.strip().upper(),)).fetchone()
        if not row:
            raise HTTPException(404, "no admission found for this token")
        if row["token_redeemed"]:
            raise HTTPException(409, "this token has already been redeemed")
        if row["status"] != "confirmed":
            raise HTTPException(400, f"admission is not ready for redemption (status: {row['status']})")
        conn.execute(
            "UPDATE admissions SET status = 'redeemed', token_redeemed = 1, ward = ?, bed_number = ? WHERE id = ?",
            (req.ward, req.bed_number, row["id"]),
        )
        row = conn.execute("SELECT * FROM admissions WHERE id = ?", (row["id"],)).fetchone()
        return admission_public(row, conn)


# ── RAG pipeline (ingestion / imaging / retrieval / advanced_rag) ──────────────

_rag_models: dict | None = None
_imaging_models: dict | None = None
_rag_lock = threading.Lock()


def get_rag_models() -> tuple[dict, dict]:
    """Lazily load the heavy RAG models once, on first use. Thread-safe."""
    global _rag_models, _imaging_models
    if _rag_models is not None:
        return _rag_models, _imaging_models

    with _rag_lock:
        if _rag_models is None:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise HTTPException(
                    500,
                    "GEMINI_API_KEY is not set. Copy .env.example to .env, "
                    "fill in your key, and restart the server.",
                )
            print("Loading RAG models — this can take a minute on first call...")
            models = ingestion.init(gemini_api_key=api_key)
            retrieval.init_reranker(models)
            _imaging_models = imaging.load_imaging_models()
            _rag_models = models
            print("RAG models ready.")

    return _rag_models, _imaging_models


class ChatRequest(BaseModel):
    patient_id: str
    question: str


@app.post("/documents/upload")
async def upload_document(
    patient_id: str = Form(...),
    uploaded_by: str = Form(...),
    requester_role: str | None = Form(None),
    requester_hospital: str | None = Form(None),
    file: UploadFile = File(...),
):
    with get_db() as conn:
        if not authorize_patient_access(conn, requester_role, uploaded_by, requester_hospital, patient_id):
            raise HTTPException(403, "you don't have access to this patient's records")

    models, imaging_models = get_rag_models()

    dest_dir = ingestion.UPLOAD_DIR / patient_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file.filename
    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    # Any image extension goes through Gemini Vision, not just filenames that
    # happen to mention a modality (e.g. "IMG_2384.jpg", WhatsApp exports) --
    # detect_modality() only picks which prompt to use; imaging.py already
    # has a sensible generic-description fallback for "unknown_scan".
    is_scan_image = dest_path.suffix.lower() in SCAN_IMAGE_EXTS

    if is_scan_image:
        result = imaging.ingest_scan(patient_id, dest_path, models, imaging_models)
        pipeline = "imaging"
        doc_type = "imaging_scan"
    else:
        result = ingestion.ingest_document(patient_id, dest_path, models)
        pipeline = "ingestion"
        doc_type = result.get("doc_type", "unknown")

    if result.get("status") != "ok":
        raise HTTPException(400, result.get("reason", "ingestion failed"))

    doc_id = uuid.uuid4().hex[:12]
    semantic_type = DOC_TYPE_DEFAULT_SEMANTIC.get(doc_type, "patient_information")

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO documents (id, patient_id, uploaded_by, file_name, doc_type, semantic_type, pipeline)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, patient_id, uploaded_by, dest_path.name, doc_type, semantic_type, pipeline),
        )
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()

    return {**dict(row), "ingest_result": result}


@app.get("/documents/{patient_id}")
def list_documents(
    patient_id: str,
    requester_id: str | None = None,
    requester_role: str | None = None,
    requester_hospital: str | None = None,
):
    with get_db() as conn:
        if requester_id and not authorize_patient_access(conn, requester_role, requester_id, requester_hospital, patient_id):
            raise HTTPException(403, "you don't have access to this patient's records")
        rows = conn.execute(
            "SELECT * FROM documents WHERE patient_id = ? ORDER BY uploaded_at",
            (patient_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/chat")
def chat(req: ChatRequest):
    models, _ = get_rag_models()
    result = advanced_rag.advanced_rag_query(req.patient_id, req.question, models)
    sources = [
        {
            "name": c.get("meta", {}).get("file_name", "unknown"),
            "doc_type": c.get("meta", {}).get("doc_type"),
        }
        for c in result.get("sources", [])
    ]
    return {
        "answer": result["answer"],
        "sources": sources,
        "confidence": result["confidence"],
        "verified": result["verified"],
        "route": result["route"],
    }
