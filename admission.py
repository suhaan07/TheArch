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

from ingestion import _AADHAAR_PAT, _PAN_PAT, _EPIC_PAT, _PASSPORT_PAT
from id_validators import (
    aadhaar_valid, pan_holder_type_valid, insurance_structure_score, DOCTOR_REG_NO_PAT,
)

GEMINI_MODEL = "gemini-2.5-flash-lite"
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
    "identity_name_match": "Name on ID matches patient",
    "insurance_policy_match": "Policy number matches form",
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


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _docs_for_slot(documents: list[dict], slot: str) -> list[dict]:
    """The most recent document uploaded into this checklist slot -- a
    "Replace file" re-upload supersedes whatever was there before rather
    than accumulating alongside it. `documents` is newest-first (server.py
    orders by uploaded_at DESC)."""
    matches = [d for d in documents if d.get("slot") == slot]
    return matches[:1]


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
        if not slot_docs:
            return ChecklistResult(item_key, 1, "missing", explanation="No identity document uploaded yet")
        d = slot_docs[0]
        text = d.get("text", "")

        aadhaar_match = _AADHAAR_PAT.search(text)
        if aadhaar_match:
            if aadhaar_valid(aadhaar_match.group()):
                return ChecklistResult(item_key, 1, "verified", d["id"], "Identity document recognized (Aadhaar checksum valid)")
            # Format matched but the number itself fails the Verhoeff checksum
            # -- could be an OCR digit error, could be made up. Not a flat
            # reject: escalate with that specific reason as context.
            return ChecklistResult(item_key, 1, "missing", d["id"],
                                    "Aadhaar number format matched but failed the standard Verhoeff checksum validation — could be an OCR digit error or a fabricated number.")

        pan_match = _PAN_PAT.search(text)
        if pan_match:
            if pan_holder_type_valid(pan_match.group()):
                return ChecklistResult(item_key, 1, "verified", d["id"], "Identity document recognized (PAN format valid)")
            return ChecklistResult(item_key, 1, "missing", d["id"],
                                    "PAN format matched but the entity-type character (4th letter) is not a valid PAN holder type — could be an OCR error or a fabricated number.")

        if _EPIC_PAT.search(text) or _PASSPORT_PAT.search(text):
            # No public checksum exists for these to verify against, but the
            # format is genuinely present -- still better than no check at all.
            return ChecklistResult(item_key, 1, "verified", d["id"], "Identity document recognized")

        # doc_type == "identity_proof" alone is just keyword scoring (e.g. "date
        # of birth", "father's name" appearing anywhere) -- it proves the page
        # is ID-shaped, not that it has a real ID number on it. Escalate
        # rather than trusting the label.
        return ChecklistResult(item_key, 1, "missing", d["id"], "No recognized ID number format (Aadhaar/PAN/Voter ID/passport) found in the document.")

    if item_key == "medical_doc":
        result = _tier1_doc_type_check(item_key, "medical_doc", MEDICAL_DOC_TYPES, documents)
        if result.status == "verified":
            doc = next((d for d in documents if d.get("id") == result.source_document_id), None)
            text = doc.get("text", "") if doc else ""
            if DOCTOR_REG_NO_PAT.search(text):
                return ChecklistResult(item_key, 1, "verified", result.source_document_id, f"{result.explanation} — doctor registration number present")
            # NMC mandates every prescription carry the doctor's registration
            # number; its total absence is a real, recognized red flag, but
            # not a flat reject -- escalate rather than auto-verify on
            # classification alone.
            return ChecklistResult(item_key, 1, "missing", result.source_document_id,
                                    f"{result.explanation}, but no doctor registration number was found anywhere in the document — Indian medical regulations require this on every prescription.")
        return result

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


_UNAVAILABLE_EXPLANATION = "Could not complete an automatic check right now — a hospital staff member will review this shortly."

def _parse_verdict(raw: str) -> dict:
    """Parse {"verdict": "verified"|"missing"|"uncertain", "explanation": "..."}
    robustly. Never echoes raw API/internal error text to the patient -- on
    any failure to get a clean verdict, falls back to a plain explanation."""
    if raw.startswith("[ERROR]"):
        return {"verdict": "uncertain", "explanation": _UNAVAILABLE_EXPLANATION}
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        try:
            result = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return {"verdict": "uncertain", "explanation": _UNAVAILABLE_EXPLANATION}
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

    # Cheap pre-check: if the patient's wording shares most of its meaningful
    # words with the document text verbatim (e.g. they copied the diagnosis
    # straight from their discharge summary), it's a confident match without
    # needing Gemini's judgement -- reserved for the genuinely different-
    # wording-same-condition cases this check exists for.
    significant_reason_words = {w for w in _words(reason) if len(w) > 3}
    if significant_reason_words and significant_reason_words <= _words(extracted):
        return ChecklistResult("diagnosis_match", 1, "verified", slot_docs[0].get("id"), "Stated reason matches the document's diagnosis text")

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


def _run_identity_name_match(admission: dict, documents: list[dict], gemini_model) -> ChecklistResult:
    """Tier 1 first: if every word of the registered name appears verbatim in
    the extracted text, that's a confident match -- no LLM needed. Anything
    less than a full match (partial OR zero overlap) escalates to Tier 2:
    OCR on a real ID photo (rotated, skewed, glare) can fail to cleanly
    extract the name region at all, so zero overlap does not reliably mean
    "different person" -- only Gemini's broader reading of the actual text
    can tell OCR noise apart from a genuine mismatch."""
    item_key = "identity_name_match"
    slot_docs = _docs_for_slot(documents, "identity")
    if not slot_docs:
        return ChecklistResult(item_key, 2, "missing", explanation="No identity document to check the name against")

    patient_name = (admission.get("patient_name") or "").strip()
    if not patient_name:
        return ChecklistResult(item_key, 2, "missing", slot_docs[0]["id"], "Patient name not on record")

    doc_text = slot_docs[0].get("text", "")
    name_words = _words(patient_name)
    if name_words and name_words <= _words(doc_text):
        return ChecklistResult(item_key, 1, "verified", slot_docs[0]["id"], "Name on the document matches the patient's registered name")

    prompt = (
        "You are checking whether a hospital admission identity document belongs to the patient being "
        "admitted -- not making any other judgement about the document.\n\n"
        f"PATIENT'S REGISTERED NAME:\n{patient_name}\n\n"
        f"TEXT EXTRACTED FROM THE IDENTITY DOCUMENT:\n{slot_docs[0].get('text', '')[:1000]}\n\n"
        "Do these refer to the same person? Allow for OCR noise, name order (first/last swapped), "
        "abbreviations, honorifics (Mr./Mrs./Dr.), and minor spelling variants. Answer \"missing\" only if "
        "they clearly appear to be different people -- this is a fraud-relevant check, so don't wave through "
        "a genuine mismatch, but don't punish OCR noise either.\n\n"
        'Respond in this exact JSON format (no markdown fences):\n'
        '{"verdict": "verified" or "missing" or "uncertain", "explanation": "one sentence, in plain '
        'language the patient can act on if not verified"}'
    )
    parsed = _parse_verdict(_gemini_call(gemini_model, prompt))
    status = "needs_review" if parsed["verdict"] == "uncertain" else parsed["verdict"]
    return ChecklistResult(item_key, 2, status, slot_docs[0]["id"], parsed["explanation"])


def _run_insurance_policy_match(admission: dict, documents: list[dict], gemini_model) -> ChecklistResult:
    """Tier 1 first: does the policy number typed into the pre-auth form
    appear verbatim in the uploaded document, AND does the document carry
    the structure a genuine policy doc/cashless card has (insurer name,
    "sum insured", TPA/IRDAI mention)? A doc_type classification of
    'insurance' alone (e.g. the word "insurance" appearing anywhere) proves
    nothing about whether it's a real, matching policy -- and neither does
    the policy number alone, since a fake page could just contain that one
    string with nothing else a real document has. Escalates to Tier 2 if
    either check falls short, since OCR noise is plausible but shouldn't be
    silently treated the same as a flatly fabricated document."""
    item_key = "insurance_policy_match"
    insurance_docs = [d for d in _docs_for_slot(documents, "insurance_policy") if d.get("doc_type") == "insurance"]
    if not insurance_docs:
        return ChecklistResult(item_key, 1, "missing", explanation="No insurance document to cross-check yet")

    doc = insurance_docs[0]
    policy_number = (admission.get("preauth") or {}).get("policy_number", "").strip()
    if not policy_number:
        return ChecklistResult(item_key, 1, "missing", doc["id"], "Enter your policy number in the pre-authorization form so it can be cross-checked against the document")

    text = doc.get("text", "")
    number_matches = policy_number.lower() in text.lower()
    if number_matches and insurance_structure_score(text) >= 1:
        return ChecklistResult(item_key, 1, "verified", doc["id"], "Policy number on the document matches the form")

    if number_matches:
        # The number matches, but the document otherwise lacks anything a
        # genuine policy document/cashless card normally has (insurer name,
        # sum insured, TPA/IRDAI mention) -- don't auto-verify on the string
        # match alone, but don't flatly reject either (could just be a
        # cropped photo). Let Gemini judge with that context.
        situation = "The policy number entered on the form was found verbatim in the document, but the document otherwise has none of the structure a real policy document/cashless card normally carries (no insurer name, no \"sum insured\", no TPA/IRDAI mention)."
    else:
        situation = "The exact policy number string was not found verbatim in the document text -- this could be OCR noise, spacing/formatting differences, or a genuinely different or fabricated policy."

    prompt = (
        "You are checking a hospital admission insurance document for consistency with the form the "
        "patient filled in -- not making a coverage decision.\n\n"
        f"POLICY NUMBER ENTERED ON THE FORM:\n{policy_number}\n\n"
        f"TEXT EXTRACTED FROM THE UPLOADED DOCUMENT:\n{text[:1000]}\n\n"
        f"{situation} Does the document plausibly belong to the same policy entered on the form, and does "
        "it look like a genuine policy document overall?\n\n"
        'Respond in this exact JSON format (no markdown fences):\n'
        '{"verdict": "verified" or "missing" or "uncertain", "explanation": "one sentence, in plain '
        'language the patient can act on if not verified"}\n'
        'Use "missing" if the document does not contain a matching or plausible policy number at all, or '
        "looks fabricated/generic (e.g. no real policy details, just the word \"insurance\")."
    )
    parsed = _parse_verdict(_gemini_call(gemini_model, prompt))
    status = "needs_review" if parsed["verdict"] == "uncertain" else parsed["verdict"]
    return ChecklistResult(item_key, 2, status, doc["id"], parsed["explanation"])


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
            # ambiguous, escalate. Whatever specific reason run_tier1 already
            # identified (e.g. a failed checksum) is kept as a hint ahead of
            # the raw text, so Gemini isn't judging blind.
            doc = next((d for d in documents if d.get("id") == r.source_document_id), None)
            if doc is not None:
                doc_text = doc.get("text", "")
                context = f"{r.explanation}\n\nDOCUMENT TEXT:\n{doc_text}" if r.explanation else doc_text
                r = ChecklistResult(item_key, 1, "missing", r.source_document_id, context)
                r = _run_escalation(item_key, r, models["gemini"])
        results.append(r)

    if any(r.item_key == "identity" and r.status == "verified" for r in results):
        results.append(_run_identity_name_match(admission, documents, models["gemini"]))

    if any(r.item_key == "insurance_policy" and r.status == "verified" for r in results):
        results.append(_run_insurance_policy_match(admission, documents, models["gemini"]))

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
