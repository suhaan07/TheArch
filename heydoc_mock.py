"""
HeyDoc — mock data and stub functions.

Every function here is a clearly labelled placeholder. The comment above each
one shows exactly what to swap in when the real backend is ready.
"""

import json
import random
import datetime
from pathlib import Path

QUEUE_FILE = Path("heydoc_queue.json")

# ── Queue helpers (shared between patient check-in and staff dashboard) ────────

_SEED_QUEUE = [
    {
        "patient_id":    "patient_002",
        "name":          "Priya Sharma",
        "department":    "Cardiology",
        "doctor":        "Dr. R. Mehta",
        "position":      1,
        "checked_in":    "09:15",
        "wait_minutes":  10,
        "status":        "active",
        "token":         "A001",
    },
    {
        "patient_id":    "patient_003",
        "name":          "Amit Verma",
        "department":    "Orthopedics",
        "doctor":        "Dr. S. Kumar",
        "position":      2,
        "checked_in":    "09:30",
        "wait_minutes":  25,
        "status":        "waiting",
        "token":         "B002",
    },
    {
        "patient_id":    "patient_004",
        "name":          "Sunita Rao",
        "department":    "General OPD",
        "doctor":        "Dr. P. Nair",
        "position":      3,
        "checked_in":    "09:45",
        "wait_minutes":  40,
        "status":        "waiting",
        "token":         "C003",
    },
]


def get_queue() -> list[dict]:
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text())
        except Exception:
            pass
    # Seed with demo patients on first run
    _write_queue(_SEED_QUEUE)
    return list(_SEED_QUEUE)


def _write_queue(q: list[dict]):
    QUEUE_FILE.write_text(json.dumps(q, indent=2))


def add_to_queue(patient_id: str, name: str, department: str, doctor: str) -> dict:
    q        = get_queue()
    position = len(q) + 1
    letters  = "ABCDEFGH"
    token    = f"{letters[(position - 1) % len(letters)]}{position:03d}"
    now      = datetime.datetime.now().strftime("%H:%M")
    entry = {
        "patient_id":   patient_id,
        "name":         name,
        "department":   department,
        "doctor":       doctor,
        "position":     position,
        "checked_in":   now,
        "wait_minutes": (position - 1) * 15 + 5,
        "status":       "waiting",
        "token":        token,
    }
    q.append(entry)
    _write_queue(q)
    return entry


def get_patient_queue_entry(patient_id: str) -> dict | None:
    return next((e for e in get_queue() if e["patient_id"] == patient_id), None)


def remove_from_queue(patient_id: str):
    q = [e for e in get_queue() if e["patient_id"] != patient_id]
    # Re-number positions
    for i, e in enumerate(q, 1):
        e["position"]    = i
        e["wait_minutes"] = max(0, (i - 1) * 15 + 5)
    _write_queue(q)


# ── Mock RAG query ─────────────────────────────────────────────────────────────
# SWAP: replace mock_rag_query with retrieval.rag_query when backend is ready.
# Signature is identical — caller in heydoc_patient.py has the swap comment.

def mock_rag_query(patient_id: str, question: str, models: dict) -> dict:
    """
    Stub that returns plausible-looking structured output.
    Real function: retrieval.rag_query(patient_id, question, models)
    """
    dummy_answers = [
        (
            "Based on your records, you were prescribed **Metformin 500mg once daily** "
            "and **Amlodipine 5mg once daily** during your visit to Max Hospital on 14/03/2023. "
            "Your discharge summary also mentions **Atorvastatin 10mg** to be continued. "
            "Please verify with your doctor before making any changes.",
            [
                {"file": "discharge_summary_2023.pdf", "doc_type": "discharge_summary", "semantic_type": "medication_history", "date": "14/03/2023", "score": 0.91},
                {"file": "prescription_march.jpg",     "doc_type": "prescription",       "semantic_type": "medication_history", "date": "14/03/2023", "score": 0.87},
            ],
            0.89,
        ),
        (
            "Your lab report from **Apollo Diagnostics dated 02/01/2024** shows an "
            "HbA1c of **8.2%** (above the target range of <7%). "
            "Your fasting blood sugar was **148 mg/dL**. Your doctor recommended a "
            "medication review at the next visit.",
            [
                {"file": "lab_report_jan2024.pdf", "doc_type": "lab_report", "semantic_type": "lab_reports", "date": "02/01/2024", "score": 0.94},
            ],
            0.94,
        ),
        (
            "According to your discharge summary from **Max Hospital (March 2023)**, "
            "your final diagnosis was **Type 2 Diabetes Mellitus** with **Stage 2 Hypertension**. "
            "The operative notes from 2021 indicate you underwent a **laparoscopic appendectomy** "
            "at Fortis Hospital with no documented complications.",
            [
                {"file": "discharge_summary_2023.pdf", "doc_type": "discharge_summary", "semantic_type": "diagnosis",         "date": "14/03/2023", "score": 0.88},
                {"file": "operative_notes_2021.pdf",   "doc_type": "operative_notes",   "semantic_type": "surgical_history",  "date": "08/06/2021", "score": 0.82},
            ],
            0.85,
        ),
    ]
    answer_text, sources, confidence = random.choice(dummy_answers)
    return {
        "answer":      answer_text,
        "sources":     sources,
        "confidence":  confidence,
        "norm_query":  question,
    }


# ── Mock intake pre-fill ───────────────────────────────────────────────────────
# SWAP: replace with real auto-fill logic (Phase 5 intake agent) when ready.
# The fields map directly to what ingestion.extract_fields() already produces,
# with allergy/insurance/emergency stubbed until the agent layer exists.

_MOCK_INTAKE_BASE = {
    "full_name":         "Rahul Kumar",
    "age":               "42",
    "gender":            "Male",
    "blood_group":       "B+",
    "allergies":         ["Penicillin", "Sulfonamides"],
    "current_medications": [
        "Metformin 500mg — once daily",
        "Amlodipine 5mg — once daily",
        "Atorvastatin 10mg — at night",
    ],
    "past_diagnoses":    [
        "Type 2 Diabetes Mellitus (2019)",
        "Stage 2 Hypertension (2020)",
    ],
    "surgical_history":  ["Laparoscopic appendectomy (2021, Fortis Hospital)"],
    "insurance": {
        "provider":   "Star Health Insurance",
        "policy_no":  "SH-2021-00XXXX",
        "valid_till": "31/03/2025",
    },
    "emergency_contact": {
        "name":         "Sunita Kumar (Spouse)",
        "phone":        "+91 98XXX XXXXX",
    },
    "last_visit_doctor":  "Dr. R. Mehta",
    "last_visit_date":    "14/03/2023",
    "last_visit_hospital": "Max Hospital, New Delhi",
}


def mock_get_intake_data(patient_id: str, models: dict) -> dict:
    """
    Stub intake pre-fill.
    Real function: intake_agent.generate_intake(patient_id, models) [Phase 5]
    """
    data = dict(_MOCK_INTAKE_BASE)
    data["patient_id"] = patient_id
    return data


# ── Mock patient directory (staff lookup) ─────────────────────────────────────

KNOWN_PATIENTS = {
    "patient_001": "Rahul Kumar",
    "patient_002": "Priya Sharma",
    "patient_003": "Amit Verma",
    "patient_004": "Sunita Rao",
    "patient_005": "Vikram Patel",
}


DEPARTMENTS = ["General OPD", "Cardiology", "Orthopedics", "Neurology", "Oncology", "Pediatrics"]
DOCTORS = {
    "General OPD":  ["Dr. P. Nair", "Dr. A. Singh"],
    "Cardiology":   ["Dr. R. Mehta", "Dr. S. Joshi"],
    "Orthopedics":  ["Dr. S. Kumar", "Dr. R. Iyer"],
    "Neurology":    ["Dr. K. Rao",   "Dr. M. Shah"],
    "Oncology":     ["Dr. V. Gupta", "Dr. N. Pillai"],
    "Pediatrics":   ["Dr. A. Bhat",  "Dr. S. Menon"],
}
