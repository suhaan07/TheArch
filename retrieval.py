"""
TheArch — Retrieval Pipeline (Phase 2)
=======================================
Hybrid RAG: vector search (bge-large cosine) + BM25 keyword search
→ RRF fusion → cross-encoder reranking → Gemini 2.5 Flash generation.
Patient-scoped: every query is filtered to a single patient_id.

Usage:
    from retrieval import rag_query, hybrid_search, init_reranker
    init_reranker(models)                        # call once after ingestion.init()
    result = rag_query(patient_id, question, models)
    # models is the dict returned by ingestion.init(), extended in-place by init_reranker
"""

import re
import time
import difflib
from typing import Optional

from rank_bm25 import BM25Okapi

# ── Config ─────────────────────────────────────────────────────────────────────

TOP_K_VECTOR      = 20      # vector candidates before RRF
TOP_K_BM25        = 20      # BM25 candidates before RRF
TOP_K_FINAL       = 5       # chunks sent to Gemini after reranking
RERANK_CANDIDATES = 20      # how many RRF results to feed the cross-encoder
MAX_CONTEXT_CHARS = 6_000   # hard truncation before sending to Gemini

SYSTEM_PROMPT = (
    "You are a medical assistant helping a doctor review a patient's health records. "
    "Answer ONLY from the provided context. Be concise and factual. "
    "If the context does not contain enough information, say so explicitly — "
    "do NOT guess or hallucinate. "
    "When citing a fact, mention which document it came from (file name and document type)."
)

GEMINI_MODEL = "gemini-2.5-flash-lite"

# ── Query normalisation ────────────────────────────────────────────────────────
# Applied before both vector encoding and BM25 tokenisation so the expanded,
# corrected query is used for retrieval. Original question is kept for the
# Gemini prompt so the answer wording matches what the user actually typed.

# Common OCR / keyboard errors where a digit is substituted for a letter inside
# a word.  Lookbehind/lookahead ensure we only fix digits that are surrounded
# by alpha characters (i.e. inside a word, not a dosage like "500mg").
_CHAR_FIX_PATTERNS: list[tuple] = [
    (re.compile(r"(?<=[a-zA-Z])0(?=[a-zA-Z])"), "o"),   # diagn0sis → diagnosis
    (re.compile(r"(?<=[a-zA-Z])3(?=[a-zA-Z])"), "e"),   # diab3tes  → diabetes
    (re.compile(r"(?<=[a-zA-Z])1(?=[a-zA-Z])"), "i"),   # d1agnosis → diagnosis
    (re.compile(r"(?<=[a-zA-Z])5(?=[a-zA-Z])"), "s"),   # diagno5is → diagnosis
    (re.compile(r"(?<=[a-zA-Z])8(?=[a-zA-Z])"), "b"),   # dia8etes  → diabetes
    (re.compile(r"(?<=[a-zA-Z])@(?=[a-zA-Z])"), "a"),   # medic@tion → medication
    (re.compile(r"\brn(?=[aeiou])"),             "m"),   # rna → ma  (rn→m OCR)
    (re.compile(r"\s{2,}"),                      " "),   # collapse whitespace
]

# Medical abbreviations that should be expanded so the embedding and BM25
# both see the full clinical term.  Keys are regex patterns (word-boundary aware).
_ABBREV_MAP: list[tuple] = [
    (re.compile(r"\bhba1c\b",  re.I), "HbA1c glycated hemoglobin"),
    (re.compile(r"\bbp\b",     re.I), "blood pressure"),
    (re.compile(r"\bhr\b",     re.I), "heart rate"),
    (re.compile(r"\brr\b",     re.I), "respiratory rate"),
    (re.compile(r"\bspo2\b",   re.I), "oxygen saturation"),
    (re.compile(r"\bdm\b",     re.I), "diabetes mellitus"),
    (re.compile(r"\bhtn\b",    re.I), "hypertension"),
    (re.compile(r"\bcad\b",    re.I), "coronary artery disease"),
    (re.compile(r"\bcopd\b",   re.I), "chronic obstructive pulmonary disease"),
    (re.compile(r"\bckd\b",    re.I), "chronic kidney disease"),
    (re.compile(r"\bckd\b",    re.I), "chronic kidney disease"),
    (re.compile(r"\bcbc\b",    re.I), "complete blood count"),
    (re.compile(r"\blft\b",    re.I), "liver function test"),
    (re.compile(r"\brft\b",    re.I), "renal function test"),
    (re.compile(r"\btsh\b",    re.I), "thyroid stimulating hormone"),
    (re.compile(r"\becg\b",    re.I), "electrocardiogram"),
    (re.compile(r"\bekg\b",    re.I), "electrocardiogram"),
    (re.compile(r"\busg\b",    re.I), "ultrasound"),
    (re.compile(r"\buti\b",    re.I), "urinary tract infection"),
    (re.compile(r"\burti\b",   re.I), "upper respiratory tract infection"),
    (re.compile(r"\blrti\b",   re.I), "lower respiratory tract infection"),
    (re.compile(r"\bmi\b",     re.I), "myocardial infarction"),
    (re.compile(r"\bicu\b",    re.I), "intensive care unit"),
    (re.compile(r"\bicu\b",    re.I), "intensive care unit"),
    (re.compile(r"\bod\b",     re.I), "once daily"),
    (re.compile(r"\bbd\b",     re.I), "twice daily"),
    (re.compile(r"\btds\b",    re.I), "three times daily"),
    (re.compile(r"\bqid\b",    re.I), "four times daily"),
    (re.compile(r"\bsos\b",    re.I), "as needed"),
    (re.compile(r"\bop\b",     re.I), "outpatient"),
    (re.compile(r"\bip\b",     re.I), "inpatient"),
    (re.compile(r"\bprn\b",    re.I), "as needed"),
    (re.compile(r"\biv\b",     re.I), "intravenous"),
    (re.compile(r"\bim\b",     re.I), "intramuscular"),
    (re.compile(r"\bsc\b",     re.I), "subcutaneous"),
    (re.compile(r"\brbs\b",    re.I), "random blood sugar"),
    (re.compile(r"\bfbs\b",    re.I), "fasting blood sugar"),
    (re.compile(r"\bppbs\b",   re.I), "postprandial blood sugar"),
    (re.compile(r"\becho\b",   re.I), "echocardiogram"),
    (re.compile(r"\befef\b",   re.I), "ejection fraction"),
    (re.compile(r"\bivf\b",    re.I), "intravenous fluids"),
    (re.compile(r"\bnsr\b",    re.I), "normal sinus rhythm"),
]

# Medical vocabulary used by difflib fuzzy correction.
# Only applied to words >= 5 characters that don't already match exactly.
_MEDICAL_VOCAB: list[str] = [
    # Conditions
    "diabetes", "hypertension", "pneumonia", "tuberculosis", "malaria", "typhoid",
    "appendicitis", "cholecystitis", "pancreatitis", "hepatitis", "cirrhosis",
    "nephritis", "pyelonephritis", "anemia", "leukemia", "lymphoma", "carcinoma",
    "infarction", "angina", "arrhythmia", "atherosclerosis", "thrombosis",
    "embolism", "hemorrhage", "fracture", "osteoporosis", "arthritis",
    "asthma", "bronchitis", "emphysema", "pleuritis", "peritonitis",
    "hypertensive", "diabetic", "cardiac", "renal", "hepatic", "pulmonary",
    "coronary", "cerebral", "vascular", "surgical", "chronic", "acute",
    # Drugs — common in Indian hospital records
    "metformin", "insulin", "glipizide", "glimepiride", "sitagliptin",
    "amlodipine", "atenolol", "metoprolol", "lisinopril", "ramipril",
    "atorvastatin", "rosuvastatin", "aspirin", "clopidogrel", "warfarin",
    "amoxicillin", "azithromycin", "ciprofloxacin", "metronidazole",
    "omeprazole", "pantoprazole", "ranitidine", "paracetamol", "ibuprofen",
    "tramadol", "morphine", "prednisolone", "dexamethasone", "furosemide",
    "spironolactone", "hydrochlorothiazide", "digoxin", "amiodarone",
    "salbutamol", "ipratropium", "budesonide", "fluticasone",
    # Lab tests
    "hemoglobin", "hematocrit", "leukocyte", "erythrocyte", "platelet",
    "creatinine", "urea", "sodium", "potassium", "chloride", "bicarbonate",
    "glucose", "cholesterol", "triglycerides", "albumin", "bilirubin",
    "alanine", "aspartate", "alkaline", "phosphatase", "amylase", "lipase",
    "hemoglobin", "hematocrit", "neutrophil", "lymphocyte", "eosinophil",
    # Procedures & doc terms
    "appendectomy", "cholecystectomy", "laparoscopy", "laparotomy",
    "colonoscopy", "endoscopy", "bronchoscopy", "catheterization",
    "angioplasty", "bypass", "hemodialysis", "biopsy", "mastectomy",
    "prescription", "discharge", "diagnosis", "medication", "surgery",
    "treatment", "admission", "investigation", "laboratory", "radiology",
    "allergies", "allergy", "symptoms", "history", "examination",
]


def _normalize_query(query: str) -> str:
    """
    Preprocess query before retrieval:
      1. Fix OCR-style digit-in-word substitutions (0→o, 3→e, 1→i …)
      2. Collapse whitespace
      3. Expand medical abbreviations (hba1c → HbA1c glycated hemoglobin, etc.)
      4. Fuzzy-correct misspelled medical terms via difflib (cutoff 0.85)

    The original query is preserved for use in the Gemini prompt.
    """
    text = query

    # Step 1 & 2: char fixes + whitespace
    for pattern, replacement in _CHAR_FIX_PATTERNS:
        text = pattern.sub(replacement, text)

    # Step 3: abbreviation expansion
    for pattern, expansion in _ABBREV_MAP:
        text = pattern.sub(expansion, text)

    # Step 4: fuzzy correction word-by-word
    words = text.split()
    corrected: list[str] = []
    for word in words:
        alpha = re.sub(r"[^a-zA-Z]", "", word)
        if len(alpha) >= 5:
            matches = difflib.get_close_matches(alpha.lower(), _MEDICAL_VOCAB, n=1, cutoff=0.85)
            if matches and matches[0] != alpha.lower():
                word = matches[0]
        corrected.append(word)

    return " ".join(corrected)


# ── Reranker ───────────────────────────────────────────────────────────────────

def init_reranker(models: dict) -> None:
    """
    Load BAAI/bge-reranker-v2-m3 cross-encoder and store it in models["reranker"].
    Call once after ingestion.init(); models dict is extended in-place.
    """
    from sentence_transformers import CrossEncoder
    print("Loading reranker (BAAI/bge-reranker-v2-m3)...")
    models["reranker"] = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
    print("  reranker OK")


def _rerank(query: str, chunks: list[dict], models: dict) -> list[dict]:
    """
    Score each (query, chunk_text) pair with the cross-encoder and return
    chunks sorted by rerank_score descending.
    No-ops if models["reranker"] is absent.
    """
    if "reranker" not in models or not chunks:
        return chunks
    reranker = models["reranker"]
    pairs    = [(query, chunk["text"]) for chunk in chunks]
    scores   = reranker.predict(pairs, show_progress_bar=False)
    for chunk, score in zip(chunks, scores):
        chunk["rerank_score"] = round(float(score), 4)
    return sorted(chunks, key=lambda x: x.get("rerank_score", 0.0), reverse=True)


# ── Tokenizer (shared with ingestion.py BM25) ──────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Keeps dosage tokens like '500mg', 'tds', 'od' intact."""
    tokens = re.findall(r"[a-z0-9]+(?:[a-z]+|[0-9]+)?", text.lower())
    return [t for t in tokens if len(t) > 1]


# ── BM25 index ─────────────────────────────────────────────────────────────────

def _build_bm25_for_patient(patient_id: str, models: dict) -> tuple:
    """
    Fetch all chunks for this patient from ChromaDB and build an in-memory
    BM25 index.  Rebuilding is fast (<1s) and keeps storage simple.

    Returns (bm25, docs, metas) — all three are empty/None when no chunks exist.
    """
    collection = models["collection"]
    result = collection.get(
        where={"patient_id": patient_id},
        include=["documents", "metadatas"],
    )
    docs  = result["documents"]
    metas = result["metadatas"]
    if not docs:
        return None, [], []
    tokenized = [_tokenize(d) for d in docs]
    bm25 = BM25Okapi(tokenized)
    return bm25, docs, metas


# ── Reciprocal Rank Fusion ─────────────────────────────────────────────────────

def _rrf(
    vector_hits: list[dict],
    bm25_hits:   list[dict],
    k:           int = 60,
) -> list[dict]:
    """
    Merge two ranked lists via Reciprocal Rank Fusion.
    Each item must have a "text" key used as the dedup key.
    Returns list sorted by rrf_score descending.
    """
    scores: dict[str, float] = {}
    items:  dict[str, dict]  = {}

    for rank, item in enumerate(vector_hits):
        key = item["text"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        items[key]  = item

    for rank, item in enumerate(bm25_hits):
        key = item["text"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        items[key]  = item

    ranked = sorted(scores, key=lambda x: scores[x], reverse=True)
    result = []
    for key in ranked:
        entry = dict(items[key])
        entry["rrf_score"] = round(scores[key], 6)
        result.append(entry)
    return result


# ── Hybrid Search ──────────────────────────────────────────────────────────────

def hybrid_search(
    patient_id:           str,
    query:                str,
    models:               dict,
    top_k:                int           = TOP_K_FINAL,
    semantic_type_filter: Optional[str] = None,
    doc_type_filter:      Optional[str] = None,
) -> list[dict]:
    """
    Hybrid vector + BM25 retrieval with RRF fusion, scoped to one patient.
    Query is normalised (abbrev expansion + typo correction) before encoding.

    Args:
        patient_id:           patient scope — only their chunks are searched
        query:                natural-language question (normalised internally)
        models:               dict returned by ingestion.init()
        top_k:                number of chunks to return after RRF
        semantic_type_filter: optional — one of patient_information / diagnosis /
                              medication_history / lab_reports / surgical_history /
                              follow_up_notes
        doc_type_filter:      optional — one of prescription / discharge_summary /
                              lab_report / biopsy_report / imaging_report /
                              operative_notes / insurance / unknown

    Returns list of dicts: {text, meta, rrf_score, [score], [bm25_score]}
    """
    norm_query = _normalize_query(query)

    embedder   = models["embedder"]
    collection = models["collection"]

    # ── Vector search ──────────────────────────────────────────────────────────
    q_vec = embedder.encode(
        f"Represent this medical document for retrieval: {norm_query}",
        normalize_embeddings=True,
    ).tolist()

    filters = [{"patient_id": patient_id}]
    if doc_type_filter:
        filters.append({"doc_type": doc_type_filter})
    if semantic_type_filter:
        filters.append({"semantic_type": semantic_type_filter})
    where = {"$and": filters} if len(filters) > 1 else filters[0]

    total = collection.count()
    n = max(1, min(TOP_K_VECTOR, total))
    vec_res = collection.query(
        query_embeddings=[q_vec],
        n_results=n,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    vector_hits: list[dict] = []
    if vec_res["documents"] and vec_res["documents"][0]:
        for text, meta, dist in zip(
            vec_res["documents"][0],
            vec_res["metadatas"][0],
            vec_res["distances"][0],
        ):
            vector_hits.append({"text": text, "meta": meta, "score": round(1 - dist, 4)})

    # ── BM25 search (on normalised query tokens) ───────────────────────────────
    bm25, all_docs, all_metas = _build_bm25_for_patient(patient_id, models)
    bm25_hits: list[dict] = []
    if bm25 and all_docs:
        q_tokens    = _tokenize(norm_query)
        bm25_scores = bm25.get_scores(q_tokens)
        ranked_idxs = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)
        for idx in ranked_idxs[:TOP_K_BM25]:
            if bm25_scores[idx] <= 0:
                continue
            meta = all_metas[idx]
            if doc_type_filter and meta.get("doc_type") != doc_type_filter:
                continue
            if semantic_type_filter and meta.get("semantic_type") != semantic_type_filter:
                continue
            bm25_hits.append({
                "text":       all_docs[idx],
                "meta":       meta,
                "bm25_score": round(float(bm25_scores[idx]), 4),
            })

    # ── RRF ───────────────────────────────────────────────────────────────────
    fused = _rrf(vector_hits, bm25_hits)
    return fused[:top_k]


# ── Context assembly ───────────────────────────────────────────────────────────

def _build_context(chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        meta     = chunk["meta"]
        date_str = f", {meta['visit_date']}" if meta.get("visit_date") else ""
        source   = (
            f"[{i}] {meta.get('file_name', 'unknown')} "
            f"({meta.get('doc_type', '?')} / {meta.get('semantic_type', '?')}{date_str})"
        )
        parts.append(f"{source}\n{chunk['text']}")
    context = "\n\n---\n\n".join(parts)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n[context truncated]"
    return context


# ── Gemini call with retry ─────────────────────────────────────────────────────

_RETRYABLE = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded")
_RETRY_DELAYS = (5, 15, 30)   # seconds between attempts 1→2, 2→3, 3→fail


def _gemini_generate(gemini_client, prompt: str) -> str:
    """
    Call Gemini with exponential backoff on 503 / 429 / overload errors.
    Raises on permanent failures (auth, bad key, etc.).
    Returns the response text.
    """
    last_err = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            resp = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"parts": [{"text": prompt}]}],
            )
            return resp.text.strip()
        except Exception as e:
            last_err = e
            err_str  = str(e)
            is_retry = any(tag in err_str for tag in _RETRYABLE)
            if is_retry and delay is not None:
                print(f"  [Gemini] attempt {attempt} failed ({err_str[:60]}…) — retrying in {delay}s")
                time.sleep(delay)
            else:
                break   # permanent error or out of retries
    raise last_err

# ── RAG query (public API) ─────────────────────────────────────────────────────

def rag_query(
    patient_id:           str,
    question:             str,
    models:               dict,
    top_k:                int           = TOP_K_FINAL,
    semantic_type_filter: Optional[str] = None,
    doc_type_filter:      Optional[str] = None,
) -> dict:
    """
    Full RAG pipeline:
      1. Normalise query
      2. Hybrid retrieve
      3. Rerank
      4. Generate answer
      5. Verify answer
      6. Calculate confidence

    Returns:
        {
            "answer": str,
            "sources": list,
            "context": str,
            "chunk_count": int,
            "norm_query": str,
            "confidence": float,
            "verified": bool,
            "prompt": str
        }
    """
    norm_question = _normalize_query(question)

    # Fetch more candidates when reranker is available
    candidates_k = RERANK_CANDIDATES if "reranker" in models else top_k

    chunks = hybrid_search(
        patient_id,
        norm_question,
        models,
        top_k=candidates_k,
        semantic_type_filter=semantic_type_filter,
        doc_type_filter=doc_type_filter,
    )

    if not chunks:
        return {
            "answer": "No records found for this patient. Upload documents first.",
            "sources": [],
            "context": "",
            "chunk_count": 0,
            "norm_query": norm_question,
            "confidence": 0,
            "verified": False,
            "prompt": "",
        }

    # ----------------------------
    # Rerank
    # ----------------------------
    if "reranker" in models:
        chunks = _rerank(norm_question, chunks, models)

    chunks = chunks[:top_k]

    # ----------------------------
    # Confidence Score
    # ----------------------------
    confidence = 0.0

    rerank_scores = [
        chunk.get("rerank_score")
        for chunk in chunks
        if "rerank_score" in chunk
    ]

    if rerank_scores:
        avg_score = sum(rerank_scores) / len(rerank_scores)

        # Scale score into 0-100 range
        confidence = round(
            max(
                0,
                min(
                    100,
                    ((avg_score + 5) / 10) * 100
                )
            ),
            1
        )

    context = _build_context(chunks)

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Patient records context:\n\n{context}\n\n"
        f"Question: {question}"
    )

    # ----------------------------
    # Main Generation
    # ----------------------------
    try:
        answer = _gemini_generate(
            models["gemini"],
            prompt
        )
    except Exception as e:
        answer = f"[Gemini error — {e}]"

    # ----------------------------
    # Verification Agent
    # ----------------------------
    verified = False

    try:
        verification_prompt = f"""
You are a medical record verification system.

Context:
{context}

Generated Answer:
{answer}

Determine whether EVERY factual claim in the generated answer is supported by the provided context.

Reply with ONLY one word:

SUPPORTED

or

NOT SUPPORTED
"""

        verification_result = _gemini_generate(
            models["gemini"],
            verification_prompt
        )

        verified = (
            "SUPPORTED"
            in verification_result.upper()
            and
            "NOT SUPPORTED"
            not in verification_result.upper()
        )

    except Exception:
        verified = False

    return {
        "answer": answer,
        "sources": chunks,
        "context": context,
        "chunk_count": len(chunks),
        "norm_query": norm_question,
        "confidence": confidence,
        "verified": verified,
        "prompt": prompt,
    }