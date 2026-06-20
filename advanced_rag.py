"""""
HeyDoc — Advanced RAG & Agentic Layer
======================================
Modular backend providing:

    Layer 1  — Patient Vault agents (timeline, admission, medication, allergy, surgery)
    Layer 2  — Hospital Intake Automation (admission summary)
    Layer 3  — Agentic AI Routing (planner, orchestrator, verification, confidence)

This file is UI-agnostic and framework-agnostic.  Import and call
``advanced_rag_query`` from any UI layer (Streamlit, FastAPI, etc.).

Public API
----------
    advanced_rag_query(patient_id, question, models)   ← main entry point
    calculate_confidence(chunks)
    verify_answer(answer, context, gemini_model)
    classify_query(query)
    planner_route(query)
    generate_patient_timeline(patient_id, collection)
    generate_admission_summary(patient_id, collection)
    get_medications(patient_id, collection)
    get_allergies(patient_id, collection)
    get_surgeries(patient_id, collection)

Depends on
----------
    retrieval.py  — rag_query(), hybrid_search()   (already in project)
    ingestion.py  — metadata schema                (already in project)
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import time
from typing import Any, Optional

# ── Logging ────────────────────────────────────────────────────────────────────

logger = logging.getLogger("heydoc.advanced_rag")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")
    )
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ── Constants ──────────────────────────────────────────────────────────────────

GEMINI_MODEL = "gemini-2.5-flash-lite"

# Confidence thresholds (0-100 scale)
CONFIDENCE_HIGH   = 75
CONFIDENCE_MEDIUM = 50

# Minimum rerank score required to count as a "strong" supporting chunk
STRONG_RERANK_THRESHOLD = 0.6

# Retry config when calling Gemini for verification / agent tasks
_RETRYABLE_TAGS   = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded")
_RETRY_DELAYS     = (5, 15, 30)

# Query-class → route mapping
_ROUTE_MAP: dict[str, str] = {
    "TIMELINE_QUERY":   "timeline_agent",
    "ADMISSION_QUERY":  "admission_agent",
    "MEDICATION_QUERY": "medication_agent",
    "ALLERGY_QUERY":    "allergy_agent",
    "SURGERY_QUERY":    "surgery_agent",
    "RAG_QUERY":        "rag_agent",
}

# Keyword sets for rule-based query classifier
_TIMELINE_KEYWORDS   = {
    "timeline", "history", "chronolog", "year", "years", "over time",
    "past", "progression", "journey", "records over", "when did",
    "first time", "previous", "sequence", "dates",
}
_ADMISSION_KEYWORDS  = {
    "admission", "admit", "intake", "hospital form", "discharge summary",
    "admit me", "admitting", "check in", "check-in", "hospitaliz",
}
_MEDICATION_KEYWORDS = {
    "medication", "medicine", "drug", "drugs", "tablet", "capsule",
    "prescription", "prescribed", "dose", "dosage", "mg", "ml",
    "taking", "currently on", "pharma", "pills", "pill",
}
_ALLERGY_KEYWORDS    = {
    "allerg", "allergic", "intoleran", "reaction", "rash", "anaphyl",
    "hypersensitiv", "contraindicated",
}
_SURGERY_KEYWORDS    = {
    "surgery", "surgeries", "surgical", "operation", "operated",
    "procedure", "appendectomy", "cholecystectomy", "laparoscop",
    "bypass", "transplant", "removal", "resection", "amputation",
    "catheteriz", "angioplasty", "stent", "incision",
}


# ══════════════════════════════════════════════════════════════════════════════
# 1.  CONFIDENCE SCORING
# ══════════════════════════════════════════════════════════════════════════════

def calculate_confidence(chunks: list[dict]) -> dict[str, Any]:
    """
    Derive a 0-100 confidence score from a list of retrieved & reranked chunks.

    Scoring components
    ------------------
    1. **Rerank signal** (40 pts): average cross-encoder ``rerank_score``
       across the top-5 chunks.  Signals how semantically relevant the
       retrieved evidence is to the query.
    2. **Retrieval signal** (30 pts): average ``rrf_score`` (or ``score``).
       Reflects fusion quality across vector + BM25 channels.
    3. **Chunk agreement** (30 pts): semantic-type diversity penalises
       low agreement (all chunks from one type → max agreement).

    Args:
        chunks: List of chunk dicts as returned by ``hybrid_search`` /
                ``rag_query`` (keys: ``text``, ``meta``, optionally
                ``rerank_score``, ``rrf_score`` / ``score``).

    Returns:
        ``{"confidence": float, "reason": str}``
        where ``confidence`` is in **[0, 100]** and ``reason`` is a
        human-readable explanation of which components drove the score.
    """
    if not chunks:
        return {
            "confidence": 0.0,
            "reason": "No chunks retrieved — no evidence available.",
        }

    top_chunks = chunks[:5]  # evaluate over at most 5 chunks

    # ── Component 1: rerank signal ─────────────────────────────────────────
    rerank_scores = [
        c.get("rerank_score", None) for c in top_chunks
    ]
    valid_rerank = [s for s in rerank_scores if s is not None]
    if valid_rerank:
        avg_rerank = statistics.mean(valid_rerank)
        # rerank scores are in [-inf, +inf] from a cross-encoder; clamp to [0,1]
        avg_rerank_norm = max(0.0, min(1.0, (avg_rerank + 1) / 2))
        rerank_points = avg_rerank_norm * 40
        rerank_note   = f"avg rerank={avg_rerank:.3f}"
    else:
        rerank_points = 20.0   # neutral if reranker was not used
        rerank_note   = "reranker not used (neutral 20/40)"

    # ── Component 2: retrieval signal ─────────────────────────────────────
    retrieval_scores = [
        c.get("rrf_score", c.get("score", 0.0)) for c in top_chunks
    ]
    avg_retrieval = statistics.mean(retrieval_scores) if retrieval_scores else 0.0
    # rrf_score is typically in [0, 1] after normalisation; vector score also [0,1]
    retrieval_points = max(0.0, min(1.0, avg_retrieval)) * 30
    retrieval_note   = f"avg retrieval={avg_retrieval:.3f}"

    # ── Component 3: chunk agreement ──────────────────────────────────────
    semantic_types = [
        c.get("meta", {}).get("semantic_type", "unknown") for c in top_chunks
    ]
    unique_types  = set(semantic_types)
    type_count    = len(unique_types)
    total_chunks  = len(top_chunks)
    # Agreement is high when chunks concentrate in few semantic types
    if total_chunks == 1:
        agreement_ratio = 1.0
    else:
        most_common_count = max(semantic_types.count(t) for t in unique_types)
        agreement_ratio   = most_common_count / total_chunks
    agreement_points = agreement_ratio * 30
    agreement_note   = (
        f"agreement={agreement_ratio:.2f} "
        f"({type_count} unique semantic type(s) across {total_chunks} chunks)"
    )

    # ── Final score ───────────────────────────────────────────────────────
    raw_score  = rerank_points + retrieval_points + agreement_points
    confidence = round(min(100.0, max(0.0, raw_score)), 1)

    if confidence >= CONFIDENCE_HIGH:
        quality = "HIGH"
    elif confidence >= CONFIDENCE_MEDIUM:
        quality = "MEDIUM"
    else:
        quality = "LOW"

    reason = (
        f"Confidence {confidence}/100 ({quality}).  "
        f"Rerank: {rerank_points:.1f}/40 ({rerank_note}).  "
        f"Retrieval: {retrieval_points:.1f}/30 ({retrieval_note}).  "
        f"Agreement: {agreement_points:.1f}/30 ({agreement_note})."
    )

    logger.debug("calculate_confidence → %s", reason)
    return {"confidence": confidence, "reason": reason}


# ══════════════════════════════════════════════════════════════════════════════
# 2.  VERIFICATION AGENT
# ══════════════════════════════════════════════════════════════════════════════

def verify_answer(
    answer: str,
    context: str,
    gemini_model,
) -> dict[str, Any]:
    """
    Verify whether every factual claim in *answer* is grounded in *context*.

    Uses Gemini as an independent verifier (reflection agent pattern):
    the model is asked to act as a medical fact-checker and judge whether
    the answer is supported by or contradicts the supplied context.

    Args:
        answer:        The LLM-generated answer to verify.
        context:       The raw context string assembled from retrieved chunks
                       (as produced by ``retrieval._build_context``).
        gemini_model:  The Gemini client from ``models["gemini"]``.

    Returns:
        ``{"verified": bool, "explanation": str}``
    """
    if not answer or not context:
        return {
            "verified": False,
            "explanation": "Verification skipped — answer or context is empty.",
        }

    verification_prompt = (
        "You are a medical fact-checking agent for a clinical AI system.\n\n"
        "Your task is to verify whether the ANSWER below is fully supported by "
        "the CONTEXT retrieved from the patient's medical records.\n\n"
        "Rules:\n"
        "- Only flag claims that are factually wrong OR cannot be found anywhere "
        "  in the CONTEXT.\n"
        "- Do NOT penalise for summarisation, paraphrasing, or minor wording "
        "  differences that preserve meaning.\n"
        "- Do NOT consider information outside the provided CONTEXT.\n\n"
        "Respond in this exact JSON format (no markdown fences):\n"
        "{\n"
        '  "verified": true or false,\n'
        '  "explanation": "one or two sentences explaining your verdict"\n'
        "}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"ANSWER:\n{answer}"
    )

    raw = _gemini_call(gemini_model, verification_prompt)

    try:
        result = json.loads(raw)
        verified    = bool(result.get("verified", False))
        explanation = str(result.get("explanation", "No explanation provided."))
    except (json.JSONDecodeError, ValueError):
        # Gemini occasionally wraps JSON in backticks — try stripping
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        try:
            result      = json.loads(cleaned)
            verified    = bool(result.get("verified", False))
            explanation = str(result.get("explanation", raw))
        except (json.JSONDecodeError, ValueError):
            # Fallback: parse "true"/"false" from the raw string
            verified    = "true" in raw.lower()
            explanation = raw[:300] if raw else "Verification response was unreadable."

    logger.info("verify_answer → verified=%s", verified)
    return {"verified": verified, "explanation": explanation}


# ══════════════════════════════════════════════════════════════════════════════
# 3.  QUERY CLASSIFIER
# ══════════════════════════════════════════════════════════════════════════════

def classify_query(query: str) -> str:
    """
    Classify an incoming question into one of six query types using purely
    rule-based / keyword matching logic (no LLM required).

    Classes
    -------
    ``TIMELINE_QUERY``   — patient history / chronological events
    ``ADMISSION_QUERY``  — hospital admission / intake form requests
    ``MEDICATION_QUERY`` — drug / prescription questions
    ``ALLERGY_QUERY``    — allergy / intolerance questions
    ``SURGERY_QUERY``    — surgical procedure history
    ``RAG_QUERY``        — general / fallback (handled by standard RAG)

    Detection is priority-ordered: ALLERGY > SURGERY > MEDICATION >
    ADMISSION > TIMELINE > RAG.  This order minimises overlap conflicts
    (e.g. "allergy to anaesthetics before surgery" is ALLERGY, not SURGERY).

    Args:
        query: Raw natural-language question from the user.

    Returns:
        One of the six class strings listed above.
    """
    q_lower = query.lower()

    def _hits(keywords: set[str]) -> bool:
        return any(kw in q_lower for kw in keywords)

    if _hits(_ALLERGY_KEYWORDS):
        label = "ALLERGY_QUERY"
    elif _hits(_SURGERY_KEYWORDS):
        label = "SURGERY_QUERY"
    elif _hits(_MEDICATION_KEYWORDS):
        label = "MEDICATION_QUERY"
    elif _hits(_ADMISSION_KEYWORDS):
        label = "ADMISSION_QUERY"
    elif _hits(_TIMELINE_KEYWORDS):
        label = "TIMELINE_QUERY"
    else:
        label = "RAG_QUERY"

    logger.info("classify_query(%r) → %s", query[:80], label)
    return label


# ══════════════════════════════════════════════════════════════════════════════
# 4.  PLANNER AGENT
# ══════════════════════════════════════════════════════════════════════════════

def planner_route(query: str) -> dict[str, str]:
    """
    Determine which specialised agent should handle the query.

    The planner classifies the query and maps it to an agent route.
    It is intentionally lightweight: it does NOT call an LLM, keeping
    latency low for the common case.

    Args:
        query: Raw natural-language question from the user.

    Returns:
        ``{"route": "<agent_name>"}``

        Possible routes:
            ``timeline_agent``   — generate chronological patient timeline
            ``admission_agent``  — generate full admission summary
            ``medication_agent`` — return medication list
            ``allergy_agent``    — return allergy list
            ``surgery_agent``    — return surgery history
            ``rag_agent``        — standard hybrid RAG (default)
    """
    query_class = classify_query(query)
    route       = _ROUTE_MAP.get(query_class, "rag_agent")
    logger.info("planner_route → %s (from class %s)", route, query_class)
    return {"route": route}


# ══════════════════════════════════════════════════════════════════════════════
# 5.  TIMELINE AGENT
# ══════════════════════════════════════════════════════════════════════════════

def generate_patient_timeline(
    patient_id: str,
    collection,
) -> dict[str, Any]:
    """
    Build a chronological medical timeline for a patient from stored metadata.

    Reads all chunks for *patient_id* from ChromaDB and aggregates the
    following metadata fields (populated during ingestion):
        ``visit_date``, ``diagnosis``, ``doctor_name``, ``hospital``,
        ``drugs``, ``surgery_type``, ``file_name``, ``doc_type``

    The result is grouped by year (falling back to "Unknown Year" if no
    date is present) and sorted chronologically.

    Args:
        patient_id: Unique patient identifier.
        collection: ChromaDB collection (``models["collection"]``).

    Returns:
        ``{
            "patient_id": str,
            "timeline": [
                {
                    "year":      str,
                    "date":      str | None,
                    "event":     str,
                    "diagnoses": list[str],
                    "drugs":     list[str],
                    "surgery":   str | None,
                    "doctor":    str | None,
                    "hospital":  str | None,
                    "source":    str,
                }
            ],
            "total_events": int
        }``
    """
    logger.info("generate_patient_timeline — patient=%s", patient_id)

    result = collection.get(
        where={"patient_id": patient_id},
        include=["metadatas"],
    )
    all_metas: list[dict] = result.get("metadatas", []) or []

    if not all_metas:
        return {
            "patient_id":   patient_id,
            "timeline":     [],
            "total_events": 0,
        }

    # De-duplicate by file_name so each document contributes one event
    seen_files: dict[str, dict] = {}
    for meta in all_metas:
        fname = meta.get("file_name", "unknown_file")
        if fname not in seen_files:
            seen_files[fname] = meta

    events: list[dict] = []
    for fname, meta in seen_files.items():
        raw_date  = meta.get("visit_date") or ""
        year      = _extract_year(raw_date) or "Unknown Year"
        diagnoses = _split_pipe(meta.get("diagnosis", ""))
        drugs     = _split_pipe(meta.get("drugs", ""))
        surgery   = meta.get("surgery_type") or None
        doctor    = meta.get("doctor_name") or None
        hospital  = meta.get("hospital") or None
        doc_type  = meta.get("doc_type", "document")

        # Build a short human-readable event description
        parts: list[str] = []
        if diagnoses:
            parts.append(f"Diagnosed: {', '.join(diagnoses)}")
        if surgery:
            parts.append(f"Surgery: {surgery}")
        if drugs:
            parts.append(f"Medications: {', '.join(drugs[:3])}")
        if not parts:
            parts.append(f"{doc_type.replace('_', ' ').title()} on file")

        events.append({
            "year":      year,
            "date":      raw_date or None,
            "event":     " | ".join(parts),
            "diagnoses": diagnoses,
            "drugs":     drugs,
            "surgery":   surgery,
            "doctor":    doctor,
            "hospital":  hospital,
            "source":    fname,
        })

    # Sort: known years first (numerically), then "Unknown Year"
    def _sort_key(e: dict) -> tuple:
        y = e["year"]
        try:
            return (0, int(y), e.get("date") or "")
        except ValueError:
            return (1, 0, e.get("date") or "")

    events.sort(key=_sort_key)

    logger.info(
        "generate_patient_timeline — %d events found for patient=%s",
        len(events), patient_id,
    )
    return {
        "patient_id":   patient_id,
        "timeline":     events,
        "total_events": len(events),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6.  ADMISSION SUMMARY AGENT
# ══════════════════════════════════════════════════════════════════════════════

def generate_admission_summary(
    patient_id: str,
    collection,
) -> dict[str, Any]:
    """
    Generate a structured hospital-admission summary by aggregating all
    ingested records for a patient.

    This is suitable for pre-populating hospital intake forms and for the
    Layer 2 Hospital Intake Automation workflow.

    Args:
        patient_id: Unique patient identifier.
        collection: ChromaDB collection (``models["collection"]``).

    Returns:
        ``{
            "patient_id": str,
            "allergies":  list[str],
            "medications": list[str],
            "diagnoses":  list[str],
            "surgeries":  list[str],
            "doctors":    list[str],
            "hospitals":  list[str],
            "latest_visit": str | None,
            "document_count": int,
        }``
    """
    logger.info("generate_admission_summary — patient=%s", patient_id)

    result = collection.get(
        where={"patient_id": patient_id},
        include=["documents", "metadatas"],
    )
    all_docs:  list[str]  = result.get("documents", []) or []
    all_metas: list[dict] = result.get("metadatas", []) or []

    if not all_metas:
        return {
            "patient_id":     patient_id,
            "allergies":      [],
            "medications":    [],
            "diagnoses":      [],
            "surgeries":      [],
            "doctors":        [],
            "hospitals":      [],
            "latest_visit":   None,
            "document_count": 0,
        }

    allergies:   set[str] = set()
    medications: set[str] = set()
    diagnoses:   set[str] = set()
    surgeries:   set[str] = set()
    doctors:     set[str] = set()
    hospitals:   set[str] = set()
    visit_dates: list[str] = []
    file_names:  set[str] = set()

    for doc_text, meta in zip(all_docs, all_metas):
        # Structured metadata fields
        for d in _split_pipe(meta.get("diagnosis", "")):
            diagnoses.add(d)
        for dr in _split_pipe(meta.get("drugs", "")):
            medications.add(dr)
        if meta.get("surgery_type"):
            surgeries.add(meta["surgery_type"])
        if meta.get("doctor_name"):
            doctors.add(meta["doctor_name"])
        if meta.get("hospital"):
            hospitals.add(meta["hospital"])
        if meta.get("visit_date"):
            visit_dates.append(meta["visit_date"])
        file_names.add(meta.get("file_name", "unknown"))

        # Allergy extraction from raw text (metadata doesn't store allergies)
        for allergy in _extract_allergies_from_text(doc_text):
            allergies.add(allergy)

    latest_visit = max(visit_dates) if visit_dates else None

    summary = {
        "patient_id":     patient_id,
        "allergies":      sorted(allergies),
        "medications":    sorted(medications),
        "diagnoses":      sorted(diagnoses),
        "surgeries":      sorted(surgeries),
        "doctors":        sorted(doctors),
        "hospitals":      sorted(hospitals),
        "latest_visit":   latest_visit,
        "document_count": len(file_names),
    }

    logger.info(
        "generate_admission_summary — diagnoses=%d, meds=%d, allergies=%d",
        len(diagnoses), len(medications), len(allergies),
    )
    return summary


# ══════════════════════════════════════════════════════════════════════════════
# 7.  MEDICATION AGENT
# ══════════════════════════════════════════════════════════════════════════════

def get_medications(
    patient_id: str,
    collection,
) -> dict[str, Any]:
    """
    Return all medications recorded across the patient's documents.

    Args:
        patient_id: Unique patient identifier.
        collection: ChromaDB collection (``models["collection"]``).

    Returns:
        ``{
            "patient_id":  str,
            "medications": list[dict],   # {name, source, date}
            "total":       int,
        }``
    """
    logger.info("get_medications — patient=%s", patient_id)

    result = collection.get(
        where={"patient_id": patient_id},
        include=["metadatas"],
    )
    all_metas: list[dict] = result.get("metadatas", []) or []

    seen: set[str] = set()
    medications: list[dict] = []

    for meta in all_metas:
        for drug in _split_pipe(meta.get("drugs", "")):
            key = f"{drug.lower()}::{meta.get('file_name', '')}"
            if key not in seen:
                seen.add(key)
                medications.append({
                    "name":   drug,
                    "source": meta.get("file_name", "unknown"),
                    "date":   meta.get("visit_date") or None,
                })

    medications.sort(key=lambda x: (x.get("date") or "", x["name"]))

    return {
        "patient_id":  patient_id,
        "medications": medications,
        "total":       len(medications),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8.  ALLERGY AGENT
# ══════════════════════════════════════════════════════════════════════════════

def get_allergies(
    patient_id: str,
    collection,
) -> dict[str, Any]:
    """
    Return all allergies and drug intolerances found in the patient's records.

    Allergies are extracted from the **raw document text** using regex
    patterns, since the ingestion pipeline does not yet store allergies
    as a dedicated metadata field.

    Args:
        patient_id: Unique patient identifier.
        collection: ChromaDB collection (``models["collection"]``).

    Returns:
        ``{
            "patient_id": str,
            "allergies":  list[dict],   # {allergen, source, date}
            "total":      int,
        }``
    """
    logger.info("get_allergies — patient=%s", patient_id)

    result = collection.get(
        where={"patient_id": patient_id},
        include=["documents", "metadatas"],
    )
    all_docs:  list[str]  = result.get("documents", []) or []
    all_metas: list[dict] = result.get("metadatas", []) or []

    seen: set[str] = set()
    allergies: list[dict] = []

    for doc_text, meta in zip(all_docs, all_metas):
        for allergen in _extract_allergies_from_text(doc_text):
            key = f"{allergen.lower()}::{meta.get('file_name', '')}"
            if key not in seen:
                seen.add(key)
                allergies.append({
                    "allergen": allergen,
                    "source":   meta.get("file_name", "unknown"),
                    "date":     meta.get("visit_date") or None,
                })

    allergies.sort(key=lambda x: x["allergen"])

    return {
        "patient_id": patient_id,
        "allergies":  allergies,
        "total":      len(allergies),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 9.  SURGERY AGENT
# ══════════════════════════════════════════════════════════════════════════════

def get_surgeries(
    patient_id: str,
    collection,
) -> dict[str, Any]:
    """
    Return the full surgical history for a patient.

    Args:
        patient_id: Unique patient identifier.
        collection: ChromaDB collection (``models["collection"]``).

    Returns:
        ``{
            "patient_id": str,
            "surgeries":  list[dict],   # {procedure, doctor, hospital, date, source}
            "total":      int,
        }``
    """
    logger.info("get_surgeries — patient=%s", patient_id)

    result = collection.get(
        where={"patient_id": patient_id},
        include=["metadatas"],
    )
    all_metas: list[dict] = result.get("metadatas", []) or []

    seen: set[str] = set()
    surgeries: list[dict] = []

    for meta in all_metas:
        surgery = meta.get("surgery_type")
        if not surgery:
            continue
        key = f"{surgery.lower()}::{meta.get('file_name', '')}"
        if key not in seen:
            seen.add(key)
            surgeries.append({
                "procedure": surgery,
                "doctor":    meta.get("doctor_name") or None,
                "hospital":  meta.get("hospital") or None,
                "date":      meta.get("visit_date") or None,
                "source":    meta.get("file_name", "unknown"),
            })

    surgeries.sort(key=lambda x: (x.get("date") or "", x["procedure"]))

    return {
        "patient_id": patient_id,
        "surgeries":  surgeries,
        "total":      len(surgeries),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 10.  AGENT ORCHESTRATOR  (main entry point)
# ══════════════════════════════════════════════════════════════════════════════

def advanced_rag_query(
    patient_id: str,
    question: str,
    models: dict,
) -> dict[str, Any]:
    """
    Main orchestrator for the HeyDoc advanced RAG & agentic layer.

    Flow
    ----
    1. **Query Classifier** — determine query class
    2. **Planner Agent** — map class to agent route
    3. **Agent Dispatch** — run the appropriate specialised agent or RAG
    4. **Verification Agent** — check answer against context (Gemini)
    5. **Confidence Scoring** — score the evidence quality

    Args:
        patient_id: Unique patient identifier (must match ChromaDB records).
        question:   Natural-language question from the user.
        models:     Dict returned by ``ingestion.init()`` and extended by
                    ``retrieval.init_reranker()``.  Expected keys:
                        ``gemini``     — Gemini client
                        ``collection`` — ChromaDB collection
                        ``embedder``   — SentenceTransformer (for RAG path)
                        ``reranker``   — CrossEncoder (optional)

    Returns:
        ``{
            "answer":       str,
            "confidence":   float,        # 0-100
            "verified":     bool,
            "sources":      list[dict],   # retrieved chunks (RAG path) or []
            "route":        str,          # agent that handled the query
            "query_class":  str,          # output of classify_query
            "metadata":     dict,         # agent-specific structured output
            "verification_explanation": str,
            "confidence_reason": str,
        }``

    If a structured agent (timeline/admission/medication/allergy/surgery)
    finds nothing — e.g. because the relevant document was classified as
    ``unknown`` at ingestion and never got its structured metadata fields
    populated — this falls back to the general ``retrieval.rag_query`` hybrid
    search instead of returning an empty "not found" answer. That path
    searches raw chunk text directly, so it can still surface a document
    the structured agents couldn't use. ``route`` reflects this as
    ``"<agent>->rag_fallback"``.
    """
    logger.info(
        "advanced_rag_query — patient=%s  question=%r",
        patient_id, question[:100],
    )
    t0 = time.monotonic()

    collection   = models["collection"]
    gemini_model = models["gemini"]

    # ── Step 1 & 2: classify + plan ───────────────────────────────────────
    query_class  = classify_query(question)
    plan         = planner_route(question)
    route        = plan["route"]

    # ── Step 3: dispatch to agent ─────────────────────────────────────────
    answer:   str        = ""
    context:  str        = ""
    sources:  list[dict] = []
    metadata: dict       = {}
    need_rag_fallback     = (route == "rag_agent")

    if route == "timeline_agent":
        agent_result = generate_patient_timeline(patient_id, collection)
        metadata     = agent_result
        if _agent_found_nothing(route, agent_result):
            need_rag_fallback = True
        else:
            answer  = _format_timeline_answer(agent_result)
            context = answer   # context == formatted output for verification

    elif route == "admission_agent":
        agent_result = generate_admission_summary(patient_id, collection)
        metadata     = agent_result
        if _agent_found_nothing(route, agent_result):
            need_rag_fallback = True
        else:
            answer  = _format_admission_answer(agent_result)
            context = answer

    elif route == "medication_agent":
        agent_result = get_medications(patient_id, collection)
        metadata     = agent_result
        if _agent_found_nothing(route, agent_result):
            need_rag_fallback = True
        else:
            answer  = _format_medications_answer(agent_result)
            context = answer

    elif route == "allergy_agent":
        agent_result = get_allergies(patient_id, collection)
        metadata     = agent_result
        if _agent_found_nothing(route, agent_result):
            need_rag_fallback = True
        else:
            answer  = _format_allergies_answer(agent_result)
            context = answer

    elif route == "surgery_agent":
        agent_result = get_surgeries(patient_id, collection)
        metadata     = agent_result
        if _agent_found_nothing(route, agent_result):
            need_rag_fallback = True
        else:
            answer  = _format_surgeries_answer(agent_result)
            context = answer

    if need_rag_fallback:
        # Either this was already the default RAG route, or the structured
        # agent above found nothing — fall back to hybrid search over raw
        # chunk text, which isn't gated on doc_type/metadata extraction.
        try:
            from retrieval import rag_query
        except ImportError as exc:
            logger.error("Could not import retrieval.rag_query: %s", exc)
            return _error_response(
                question, query_class, route,
                f"retrieval module not available: {exc}",
            )

        if route != "rag_agent":
            logger.info(
                "advanced_rag_query — %s found nothing, falling back to rag_agent",
                route,
            )

        rag_result = rag_query(patient_id, question, models)
        answer     = rag_result.get("answer", "")
        context    = rag_result.get("context", "")
        sources    = rag_result.get("sources", [])
        metadata   = {
            **metadata,
            "norm_query":  rag_result.get("norm_query", ""),
            "chunk_count": rag_result.get("chunk_count", 0),
        }
        if route != "rag_agent":
            route = f"{route}->rag_fallback"

    # ── Step 4: verification ──────────────────────────────────────────────
    verification = verify_answer(answer, context, gemini_model)

    # ── Step 5: confidence scoring ────────────────────────────────────────
    confidence_result = calculate_confidence(sources) if sources else _agent_confidence(answer)

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "advanced_rag_query complete — route=%s  confidence=%.1f  verified=%s  elapsed=%.2fs",
        route, confidence_result["confidence"], verification["verified"], elapsed,
    )

    return {
        "answer":                    answer,
        "confidence":                confidence_result["confidence"],
        "verified":                  verification["verified"],
        "sources":                   sources,
        "route":                     route,
        "query_class":               query_class,
        "metadata":                  metadata,
        "verification_explanation":  verification["explanation"],
        "confidence_reason":         confidence_result["reason"],
        "elapsed_seconds":           elapsed,
    }


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _gemini_call(gemini_model, prompt: str) -> str:
    """
    Call Gemini with retry logic for transient errors (503, 429, overload).
    Returns the response text, or an error string prefixed with ``[ERROR]``.
    """
    last_err = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            resp = gemini_model.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"parts": [{"text": prompt}]}],
            )
            return resp.text.strip()
        except Exception as exc:
            last_err   = exc
            err_str    = str(exc)
            is_retry   = any(tag in err_str for tag in _RETRYABLE_TAGS)
            if is_retry and delay is not None:
                logger.warning(
                    "[Gemini] attempt %d failed (%s…) — retrying in %ds",
                    attempt, err_str[:60], delay,
                )
                time.sleep(delay)
            else:
                break
    logger.error("[Gemini] permanent failure: %s", last_err)
    return f"[ERROR] Gemini call failed: {last_err}"


def _agent_found_nothing(route: str, agent_result: dict) -> bool:
    """True if a structured agent's result is empty — i.e. it has nothing
    to answer with, so advanced_rag_query should fall back to rag_agent."""
    if route == "timeline_agent":
        return agent_result.get("total_events", 0) == 0
    if route == "admission_agent":
        return not any(agent_result.get(k) for k in ("diagnoses", "medications", "allergies", "surgeries"))
    if route in ("medication_agent", "allergy_agent", "surgery_agent"):
        return agent_result.get("total", 0) == 0
    return False


def _split_pipe(value: str) -> list[str]:
    """Split a pipe-delimited metadata string into a cleaned list."""
    if not value:
        return []
    return [v.strip() for v in value.split("|") if v.strip()]


def _extract_year(date_str: str) -> Optional[str]:
    """Extract a 4-digit year from a date string, or None."""
    if not date_str:
        return None
    m = re.search(r"\b(19|20)\d{2}\b", date_str)
    return m.group(0) if m else None


_ALLERGY_PATTERN = re.compile(
    r"(?:allerg(?:ic|y|ies)\s+to|hypersensitive\s+to|intolerant\s+to|"
    r"known\s+allerg(?:y|ies)[:\s]+|NKDA|no\s+known\s+drug\s+allergies)"
    r"(?:[:\s]+)?([\w\s,/\-]+?)(?:\.|,\s+(?:and\s+)?(?:[A-Z]|\d)|$)",
    re.IGNORECASE,
)
_NKDA_PATTERN = re.compile(r"\b(?:NKDA|no\s+known\s+drug\s+allerg(?:y|ies))\b", re.IGNORECASE)


def _extract_allergies_from_text(text: str) -> list[str]:
    """
    Extract allergen names from raw document text using regex patterns.
    Returns a list of trimmed allergen strings (may be empty).
    """
    if not text:
        return []

    # Explicit no-allergy marker
    if _NKDA_PATTERN.search(text):
        return ["NKDA (No Known Drug Allergies)"]

    results: list[str] = []
    for match in _ALLERGY_PATTERN.finditer(text):
        allergen = match.group(1).strip().rstrip(".,;")
        if allergen and len(allergen) > 2:
            results.append(allergen)

    return results


def _agent_confidence(answer: str) -> dict[str, Any]:
    """
    Return a synthetic confidence dict for structured-agent routes
    (timeline, admission, etc.) that do not produce ranked chunks.
    Scores are based on answer completeness rather than retrieval quality.
    """
    if not answer or "no records" in answer.lower() or "no " in answer.lower()[:30]:
        return {
            "confidence": 40.0,
            "reason": "Agent returned a partial or empty result — confidence is moderate.",
        }
    return {
        "confidence": 85.0,
        "reason": (
            "Structured agent answer derived directly from stored metadata — "
            "high confidence (no retrieval uncertainty)."
        ),
    }


def _error_response(
    question: str,
    query_class: str,
    route: str,
    reason: str,
) -> dict[str, Any]:
    """Build a standardised error response dict."""
    return {
        "answer":                   f"An error occurred: {reason}",
        "confidence":               0.0,
        "verified":                 False,
        "sources":                  [],
        "route":                    route,
        "query_class":              query_class,
        "metadata":                 {"error": reason},
        "verification_explanation": "Verification could not be performed.",
        "confidence_reason":        "Error during query processing.",
        "elapsed_seconds":          0.0,
    }


# ── Answer formatters ─────────────────────────────────────────────────────────

def _format_timeline_answer(result: dict) -> str:
    """Convert timeline agent output to a readable markdown-style string."""
    timeline = result.get("timeline", [])
    if not timeline:
        return "No medical history records found for this patient."

    lines = [f"Medical Timeline — {result['patient_id']}", "=" * 50, ""]
    current_year = None
    for event in timeline:
        if event["year"] != current_year:
            current_year = event["year"]
            lines.append(f"\n{current_year}")
            lines.append("-" * len(current_year))
        lines.append(f"  • {event['event']}")
        if event.get("doctor"):
            lines.append(f"    Doctor: {event['doctor']}")
        if event.get("hospital"):
            lines.append(f"    Hospital: {event['hospital']}")
        if event.get("date") and event["date"] != event["year"]:
            lines.append(f"    Date: {event['date']}")
        lines.append(f"    Source: {event['source']}")
    lines.append(f"\n[{result['total_events']} event(s) found]")
    return "\n".join(lines)


def _format_admission_answer(result: dict) -> str:
    """Convert admission summary to a readable form-style string."""
    if not result.get("diagnoses") and not result.get("medications"):
        return "No records found to generate an admission summary."

    def _items(lst: list, bullet: str = "•") -> list[str]:
        return [f"  {bullet} {x}" for x in lst] if lst else ["  None on record"]

    lines: list[str] = [
        f"Admission Summary — {result['patient_id']}",
        "=" * 50,
        f"Documents on file: {result.get('document_count', 0)}",
        f"Latest visit: {result.get('latest_visit') or 'Unknown'}",
        "",
        "ALLERGIES:",
    ]
    lines += _items(result["allergies"])
    lines += ["", "CURRENT MEDICATIONS:"]
    lines += _items(result["medications"])
    lines += ["", "DIAGNOSES / CONDITIONS:"]
    lines += _items(result["diagnoses"])
    lines += ["", "SURGICAL HISTORY:"]
    lines += _items(result["surgeries"])
    lines += ["", "TREATING DOCTORS:"]
    lines += _items(result["doctors"])
    lines += ["", "HOSPITALS:"]
    lines += _items(result["hospitals"])
    return "\n".join(lines)


def _format_medications_answer(result: dict) -> str:
    """Convert medication list to a readable string."""
    meds = result.get("medications", [])
    if not meds:
        return "No medications found in this patient's records."

    lines = [
        f"Medications — {result['patient_id']}",
        "=" * 40,
        f"Total: {result['total']}",
        "",
    ]
    for m in meds:
        date_part = f"  [{m['date']}]" if m.get("date") else ""
        lines.append(f"  • {m['name']}{date_part}  (from: {m['source']})")
    return "\n".join(lines)


def _format_allergies_answer(result: dict) -> str:
    """Convert allergy list to a readable string."""
    allergies = result.get("allergies", [])
    if not allergies:
        return "No allergies found in this patient's records."

    lines = [
        f"Allergies — {result['patient_id']}",
        "=" * 40,
        f"Total: {result['total']}",
        "",
    ]
    for a in allergies:
        date_part = f"  [{a['date']}]" if a.get("date") else ""
        lines.append(f"  ⚠ {a['allergen']}{date_part}  (from: {a['source']})")
    return "\n".join(lines)


def _format_surgeries_answer(result: dict) -> str:
    """Convert surgery history to a readable string."""
    surgeries = result.get("surgeries", [])
    if not surgeries:
        return "No surgical procedures found in this patient's records."

    lines = [
        f"Surgical History — {result['patient_id']}",
        "=" * 40,
        f"Total procedures: {result['total']}",
        "",
    ]
    for s in surgeries:
        lines.append(f"  • {s['procedure']}")
        if s.get("date"):
            lines.append(f"    Date: {s['date']}")
        if s.get("doctor"):
            lines.append(f"    Surgeon: {s['doctor']}")
        if s.get("hospital"):
            lines.append(f"    Hospital: {s['hospital']}")
        lines.append(f"    Source: {s['source']}")
    return "\n".join(lines)