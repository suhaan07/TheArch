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
Requires a .env file (see .env.example) with GEMINI_API_KEY set.
"""
import datetime
import hashlib
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
    "unknown": "patient_information",
}

SCAN_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}

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
def list_patients():
    """All signed-up patients — lets doctor/tpa/lab pick a real patient to upload for."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name FROM users WHERE role = 'patient' ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/doctors")
def list_doctors():
    """All signed-up doctors with their availability — lets a patient pick one to book."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, dept, room, hospital, timings FROM users WHERE role = 'doctor' ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


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
    if req.status not in {"pending", "accepted", "declined"}:
        raise HTTPException(400, "status must be 'pending', 'accepted', or 'declined'")
    with get_db() as conn:
        if not conn.execute("SELECT id FROM appointments WHERE id = ?", (appointment_id,)).fetchone():
            raise HTTPException(404, "appointment not found")
        conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (req.status, appointment_id))
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return appointment_public(row, conn)


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
    file: UploadFile = File(...),
):
    models, imaging_models = get_rag_models()

    dest_dir = ingestion.UPLOAD_DIR / patient_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file.filename
    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    is_scan_image = (
        dest_path.suffix.lower() in SCAN_IMAGE_EXTS
        and imaging.detect_modality(dest_path) != "unknown_scan"
    )

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
def list_documents(patient_id: str):
    with get_db() as conn:
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
