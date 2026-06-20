"""
HeyDoc — Admission verification engine (Tier 1 rules + Tier 2 Gemini reasoning)
=================================================================================
Two-tier checklist verification for the pre-admission flow:

    Tier 1 — deterministic rule checks (doc_type membership, regex, field
             presence/numeric comparisons). No LLM call. Runs first, resolves
             the large majority of items.
    Tier 2 — Gemini reasoning, only for items Tier 1 genuinely can't decide:
             the always-semantic 'diagnosis_match', and any other item where
             a document was uploaded into that slot but didn't cleanly
             classify/pattern-match (ambiguous, not just absent).

This file is storage-agnostic, same spirit as advanced_rag.py sitting beside
retrieval.py — server.py assembles the plain-dict inputs (querying ChromaDB
for each document's extracted text/metadata) and persists the results.

Public API
----------
    required_items(payment_path, is_corporate, estimated_cost) -> list[str]
    verify_admission(admission, documents, models) -> list[ChecklistResult]
    generate_token(existing_tokens) -> str
"""
from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from ingestion import _AADHAAR_PAT, _PAN_PAT

GEMINI_MODEL = "gemini-2.5-flash"
_RETRYABLE_TAGS = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded")
_RETRY_DELAYS = (5, 15, 30)

MEDICAL_DOC_TYPES = {"prescription", "discharge_summary", "operative_notes"}

ITEM_LABELS = {
    "identity": "Identity proof",
    "medical_doc": "Medical document",
    "insurance_policy": "Insurance policy",
    "preauth_form": "Pre-authorization form",
    "kyc_pan": "KYC (PAN)",
    "employee_id": "Employee ID",
    "diagnosis_match": "Diagnosis match",
}


@dataclass
class ChecklistResult:
    item_key: str
    tier: int
    status: str  # 'verified' | 'missing' | 'needs_review'
    source_document_id: Optional[str] = None
    explanation: str = ""


def required_items(payment_path: str, is_corporate: bool, estimated_cost: Optional[int]) -> list[str]:
    """Which checklist item_keys apply, given the chosen path and form answers."""
    items = ["identity", "medical_doc"]
    if payment_path == "insurance":
        items += ["insurance_policy", "preauth_form"]
        if estimated_cost is not None and estimated_cost >= 100_000:
            items.append("kyc_pan")
        if is_corporate:
            items.append("employee_id")
    return items


def _docs_for_slot(documents: list[dict], slot: str) -> list[dict]:
    """Documents the patient uploaded specifically into this checklist slot."""
    return [d for d in documents if d.get("slot") == slot]


def _tier1_doc_type_check(item_key: str, slot: str, valid_types: set[str], documents: list[dict]) -> ChecklistResult:
    slot_docs = _docs_for_slot(documents, slot)
    for d in slot_docs:
        if d.get("doc_type") in valid_types:
            return ChecklistResult(item_key, 1, "verified", d["id"], f"Classified as {d['doc_type']}")
    label = ITEM_LABELS.get(item_key, item_key)
    if slot_docs:
        # A document exists but didn't cleanly classify — ambiguous, not absent.
        return ChecklistResult(item_key, 1, "missing", slot_docs[0]["id"], f"{label}: uploaded document didn't classify as expected — needs a closer look")
    return ChecklistResult(item_key, 1, "missing", explanation=f"No {label.lower()} uploaded yet")


def run_tier1(item_key: str, admission: dict, documents: list[dict]) -> ChecklistResult:
    """Deterministic check for one item — no LLM call."""
    if item_key == "preauth_form":
        preauth = admission.get("preauth") or {}
        required_fields = ("policy_number", "sum_insured", "estimated_cost", "diagnosis", "length_of_stay", "room_category")
        missing_fields = [f for f in required_fields if not preauth.get(f)]
        if missing_fields:
            return ChecklistResult(item_key, 1, "missing", explanation=f"Missing fields: {', '.join(missing_fields)}")
        return ChecklistResult(item_key, 1, "verified", explanation="All pre-authorization fields completed")

    if item_key == "identity":
        slot_docs = _docs_for_slot(documents, "identity")
        for d in slot_docs:
            if d.get("doc_type") == "identity_proof" or _AADHAAR_PAT.search(d.get("text", "")) or _PAN_PAT.search(d.get("text", "")):
                return ChecklistResult(item_key, 1, "verified", d["id"], "Identity document recognized")
        if slot_docs:
            return ChecklistResult(item_key, 1, "missing", slot_docs[0]["id"], "Uploaded document didn't match an ID format — needs a closer look")
        return ChecklistResult(item_key, 1, "missing", explanation="No identity document uploaded yet")

    if item_key == "medical_doc":
        return _tier1_doc_type_check(item_key, "medical_doc", MEDICAL_DOC_TYPES, documents)

    if item_key == "insurance_policy":
        return _tier1_doc_type_check(item_key, "insurance_policy", {"insurance"}, documents)

    if item_key == "kyc_pan":
        slot_docs = _docs_for_slot(documents, "kyc_pan")
        for d in slot_docs:
            if _PAN_PAT.search(d.get("text", "")):
                return ChecklistResult(item_key, 1, "verified", d["id"], "PAN number pattern found")
        return ChecklistResult(item_key, 1, "missing", explanation="No PAN card detected — required since estimated cost is ₹1 lakh or more")

    if item_key == "employee_id":
        slot_docs = _docs_for_slot(documents, "employee_id")
        if slot_docs:
            return ChecklistResult(item_key, 1, "verified", slot_docs[0]["id"], "Employee ID document uploaded")
        return ChecklistResult(item_key, 1, "missing", explanation="No employee ID uploaded yet")

    raise ValueError(f"unknown Tier 1 item_key: {item_key}")


def _gemini_call(gemini_model, prompt: str) -> str:
    last_err = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            resp = gemini_model.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"parts": [{"text": prompt}]}],
            )
            return resp.text.strip()
        except Exception as exc:
            last_err = exc
            err_str = str(exc)
            if any(tag in err_str for tag in _RETRYABLE_TAGS) and delay is not None:
                time.sleep(delay)
            else:
                break
    return f"[ERROR] Gemini call failed: {last_err}"


def _parse_verdict(raw: str) -> dict:
    """Parse {"verdict": "verified"|"missing"|"uncertain", "explanation": "..."} robustly."""
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        try:
            result = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return {"verdict": "uncertain", "explanation": raw[:300] if raw else "Could not parse the verification response."}
    verdict = str(result.get("verdict", "uncertain")).lower()
    if verdict not in ("verified", "missing", "uncertain"):
        verdict = "uncertain"
    explanation = str(result.get("explanation", "No explanation provided."))
    return {"verdict": verdict, "explanation": explanation}


def _run_diagnosis_match(admission: dict, documents: list[dict], gemini_model) -> ChecklistResult:
    slot_docs = _docs_for_slot(documents, "medical_doc")
    reason = (admission.get("admission_reason") or "").strip()
    if not slot_docs or not reason:
        return ChecklistResult("diagnosis_match", 2, "missing", explanation="Need both a medical document and a stated admission reason to compare")

    extracted = slot_docs[0].get("diagnosis") or slot_docs[0].get("text", "")[:500]
    prompt = (
        "You are a medical admissions clerk checking paperwork consistency, not making a clinical "
        "judgement. Compare the PATIENT'S STATED REASON for admission against the DIAGNOSIS extracted "
        "from their medical document. They're consistent if they describe the same underlying condition, "
        "even worded very differently (e.g. 'recurrent dermoid cyst' and 'nose surgery' can be the same "
        "thing).\n\n"
        f"PATIENT'S STATED REASON:\n{reason}\n\n"
        f"DIAGNOSIS / DOCUMENT TEXT:\n{extracted}\n\n"
        'Respond in this exact JSON format (no markdown fences):\n'
        '{"verdict": "verified" or "missing" or "uncertain", "explanation": "one sentence, in plain '
        'language the patient can act on if not verified"}\n'
        'Use "missing" only if they clearly describe different, unrelated conditions. Use "uncertain" '
        "only if you genuinely cannot tell either way."
    )
    parsed = _parse_verdict(_gemini_call(gemini_model, prompt))
    status = "needs_review" if parsed["verdict"] == "uncertain" else parsed["verdict"]
    return ChecklistResult("diagnosis_match", 2, status, slot_docs[0].get("id"), parsed["explanation"])


def _run_escalation(item_key: str, prior: ChecklistResult, gemini_model) -> ChecklistResult:
    """Tier 1 found a document in this slot but couldn't classify/pattern-match it confidently."""
    label = ITEM_LABELS.get(item_key, item_key)
    prompt = (
        f"You are checking a hospital admission document against one checklist requirement: \"{label}\".\n"
        "The document didn't cleanly match our automatic classifier, so use your judgement on the raw "
        "extracted text below. Does this document genuinely satisfy the requirement?\n\n"
        f"EXTRACTED TEXT:\n{prior.explanation}\n\n"
        'Respond in this exact JSON format (no markdown fences):\n'
        '{"verdict": "verified" or "missing" or "uncertain", "explanation": "one sentence, in plain '
        'language the patient can act on if not verified"}'
    )
    parsed = _parse_verdict(_gemini_call(gemini_model, prompt))
    status = "needs_review" if parsed["verdict"] == "uncertain" else parsed["verdict"]
    return ChecklistResult(item_key, 2, status, prior.source_document_id, parsed["explanation"])


def verify_admission(admission: dict, documents: list[dict], models: dict) -> list[ChecklistResult]:
    """
    Run the full checklist for one admission: Tier 1 first for every
    applicable item; Tier 2 only for items where a document was uploaded but
    Tier 1 couldn't confirm it (ambiguous, not absent), plus the always-Tier-2
    'diagnosis_match' once a medical document is present at all.
    """
    items = required_items(
        admission.get("payment_path", "self_pay"),
        bool(admission.get("is_corporate")),
        admission.get("estimated_cost"),
    )

    results: list[ChecklistResult] = []
    for item_key in items:
        r = run_tier1(item_key, admission, documents)
        if r.status == "missing" and r.source_document_id and item_key != "preauth_form":
            # A document exists for this slot but Tier 1 couldn't confirm it —
            # ambiguous, escalate. Pass the doc's text through via .explanation
            # so the Tier 2 call doesn't need to re-look-up the document.
            doc = next((d for d in documents if d.get("id") == r.source_document_id), None)
            if doc is not None:
                r = ChecklistResult(item_key, 1, "missing", r.source_document_id, doc.get("text", ""))
                r = _run_escalation(item_key, r, models["gemini"])
        results.append(r)

    if any(r.item_key == "medical_doc" and r.status == "verified" for r in results):
        results.append(_run_diagnosis_match(admission, documents, models["gemini"]))

    return results


def generate_token(existing_tokens: set[str]) -> str:
    """8-char unambiguous alphanumeric token (no 0/O/1/I) — typeable by hand, collision-checked."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        token = "".join(secrets.choice(alphabet) for _ in range(8))
        if token not in existing_tokens:
            return token
