"""
TheArch — Ingestion Pipeline
============================
Full document ingestion pipeline: OCR → classify → extract → chunk → embed → store.

Usage (in Colab or any Python environment):
    from ingestion import init, ingest_document, vector_search, inspect_all_chunks

    models = init(gemini_api_key="AIza...")
    result = ingest_document("patient_001", "/path/to/file.pdf", models)
    results = vector_search("patient_001", "what surgery did I have?", models)
"""

import os
import re
import json
import hashlib
import datetime
import base64
import io
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
# THEARCH_DATA_DIR lets this run locally (FastAPI/server.py) or in Colab —
# set it to "/content/drive/MyDrive/TheArch" in a Colab notebook to keep the
# old persistent-to-Drive behaviour; defaults to a local folder otherwise.

DRIVE_BASE  = Path(os.environ.get("THEARCH_DATA_DIR", Path(__file__).resolve().parent / "data"))
CHROMA_DIR  = DRIVE_BASE / "chroma_db"
UPLOAD_DIR  = DRIVE_BASE / "uploads"
LOCAL_BASE  = DRIVE_BASE / "scratch"

DIGITAL_CHAR_THRESHOLD = 50
CHUNK_SIZE             = 384
CHUNK_OVERLAP          = 48
EMBED_MODEL_NAME       = "BAAI/bge-large-en-v1.5"
# INT8-quantized ONNX copy of the same model — used in production instead
# (THEARCH_QUANTIZED=1) to fit Railway's memory limit. Same weights, lower
# precision; `.encode()` behaves identically. Local dev never touches this.
EMBED_MODEL_NAME_QUANTIZED = "suhaan7988/bge-large-en-v1.5-int8-onnx"
EMBED_BATCH_SIZE       = 32
CHROMA_COLLECTION      = "thearch_docs"

DOCTR_CONF_THRESHOLD   = 0.80   # below this → escalate to Gemini
DOCTR_MIN_CHARS        = 30     # below this → docTR effectively failed
GEMINI_MIN_CHARS       = 50     # Gemini must return at least this to be used

OCR_PROMPT = (
    "This is a scanned page from an Indian hospital medical record. "
    "Transcribe ALL text exactly as written, including handwritten notes. "
    "Preserve layout. Do not interpret or summarise -- only transcribe. "
    "For uncertain handwritten words wrap your best guess in [brackets]."
)


# ── Init ──────────────────────────────────────────────────────────────────────

def init(gemini_api_key: str) -> dict:
    """
    Load all models and return a models dict.
    Call once per session — pass the returned dict to all other functions.

    Returns:
        {
            "ocr":      docTR ocr_predictor,
            "embedder": SentenceTransformer,
            "splitter": LlamaIndex SentenceSplitter,
            "collection": ChromaDB collection,
            "gemini":   google.genai Client,
        }
    """
    for d in [CHROMA_DIR, UPLOAD_DIR, LOCAL_BASE]:
        d.mkdir(parents=True, exist_ok=True)

    from doctr.models import ocr_predictor
    from sentence_transformers import SentenceTransformer
    from llama_index.core.node_parser import SentenceSplitter
    import chromadb
    from chromadb.config import Settings
    import google.genai as genai

    print("Loading docTR...")
    ocr_model = ocr_predictor(pretrained=True)
    print("  docTR OK")

    if os.environ.get("THEARCH_QUANTIZED") == "1":
        print(f"Loading embedder, quantized ({EMBED_MODEL_NAME_QUANTIZED})...")
        embedder = SentenceTransformer(
            EMBED_MODEL_NAME_QUANTIZED, backend="onnx",
            model_kwargs={"file_name": "onnx/model_int8.onnx"},
        )
    else:
        print(f"Loading embedder ({EMBED_MODEL_NAME})...")
        embedder = SentenceTransformer(EMBED_MODEL_NAME)
    print("  embedder OK")

    splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

    chroma_client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = chroma_client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"  ChromaDB ready — {collection.count()} existing chunks")

    gemini_client = genai.Client(api_key=gemini_api_key)
    print("  Gemini client ready")

    return {
        "ocr":        ocr_model,
        "embedder":   embedder,
        "splitter":   splitter,
        "collection": collection,
        "gemini":     gemini_client,
    }


# ── OCR Layer ─────────────────────────────────────────────────────────────────

def _page_to_b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _is_digital_pdf(path: Path) -> bool:
    """True if PDF has a real text layer (>= DIGITAL_CHAR_THRESHOLD chars)."""
    if path.suffix.lower() not in {".pdf"}:
        return False
    try:
        import fitz
        doc   = fitz.open(str(path))
        total = 0
        for page in doc:
            total += len(page.get_text("text").strip())
            if total >= DIGITAL_CHAR_THRESHOLD:
                doc.close()
                return True
        doc.close()
    except Exception as e:
        print(f"  [WARN] {path.name}: {e}")
    return False


def _extract_pymupdf(path: Path) -> str:
    import fitz
    doc   = fitz.open(str(path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if text:
            pages.append(f"[PAGE {i+1}]\n{text}")
    doc.close()
    return "\n\n".join(pages)


def _extract_doctr(path: Path, ocr_model) -> tuple[str, float]:
    """Returns (text, avg_word_confidence)."""
    from doctr.io import DocumentFile
    if path.suffix.lower() == ".pdf":
        doc_input = DocumentFile.from_pdf(str(path))
    else:
        doc_input = DocumentFile.from_images([str(path)])
    result = ocr_model(doc_input)
    lines, confs = [], []
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                lines.append(" ".join(w.value for w in line.words))
                confs.extend(w.confidence for w in line.words)
        lines.append("")
    text     = "\n".join(lines).strip()
    avg_conf = round(sum(confs) / len(confs), 4) if confs else 0.0
    return text, avg_conf


def _looks_like_garbage(text: str) -> bool:
    """docTR can report high per-word confidence on individual misread
    characters when a photo is rotated or skewed -- it's confidently reading
    the wrong thing, not uncertain about the right thing, so the confidence
    score alone doesn't catch it. Flag text where most "words" are 1-2
    characters as suspect regardless of reported confidence."""
    tokens = text.split()
    if not tokens:
        return True
    short = sum(1 for t in tokens if len(t) <= 2)
    return short / len(tokens) > 0.5


def _extract_gemini_pdf(path: Path, gemini_client) -> str:
    """Rasterise each PDF page and send to Gemini Vision."""
    import fitz
    from PIL import Image as PILImage
    doc       = fitz.open(str(path))
    all_pages = []
    for page in doc:
        mat = fitz.Matrix(200 / 72, 200 / 72)
        pix = page.get_pixmap(matrix=mat)
        img = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
        for attempt in range(3):
            try:
                resp = gemini_client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=[{"parts": [
                        {"inline_data": {"mime_type": "image/png", "data": _page_to_b64(img)}},
                        {"text": OCR_PROMPT},
                    ]}],
                )
                all_pages.append(resp.text.strip())
                break
            except Exception:
                if attempt < 2:
                    time.sleep((attempt + 1) * 10)
                else:
                    all_pages.append("")
        time.sleep(2)
    doc.close()
    return "\n\n[PAGE BREAK]\n\n".join(all_pages)


def _extract_gemini_image(path: Path, gemini_client) -> str:
    from PIL import Image as PILImage
    img = PILImage.open(str(path)).convert("RGB")
    for attempt in range(3):
        try:
            resp = gemini_client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=[{"parts": [
                    {"inline_data": {"mime_type": "image/png", "data": _page_to_b64(img)}},
                    {"text": OCR_PROMPT},
                ]}],
            )
            return resp.text.strip()
        except Exception:
            if attempt < 2:
                time.sleep((attempt + 1) * 10)
    return ""


def extract_text(path: Path, models: dict) -> tuple[str, str]:
    """
    Hybrid OCR pipeline:

      0. Plain text (.txt/.md)     → read directly
      1. Digital PDF               → PyMuPDF
         If that text doesn't classify into any known doc_type, its embedded
         text layer is probably unreliable (e.g. scanner software embedding
         its own low-quality OCR pass under a clean printed letterhead) —
         escalate to Tier 2 and keep whichever result actually classifies.
      2. Scanned PDF / image
         a. docTR conf >= 0.80     → use docTR       (printed/typed)
         b. docTR conf <  0.80     → Gemini Vision   (handwritten)
            Gemini > docTR chars   → use Gemini
            else                   → docTR fallback

    Returns (text, method_used).
    method_used: 'plaintext' | 'pymupdf' | 'doctr' | 'gemini' | 'doctr_fallback'
    """
    is_image = path.suffix.lower() in {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}

    # Tier 0
    if path.suffix.lower() in {".txt", ".md", ".text"}:
        print(f"    [plaintext] {path.name}")
        return path.read_text(errors="replace"), "plaintext"

    # Tier 1
    pymupdf_text = None
    if _is_digital_pdf(path):
        print(f"    [pymupdf]   {path.name}")
        pymupdf_text = _extract_pymupdf(path)
        if classify_document(pymupdf_text) != "unknown":
            return pymupdf_text, "pymupdf"
        print(f"    [pymupdf]   text layer didn't match any known document type "
              f"— embedded text layer looks unreliable, escalating to OCR")

       # Tier 2a — Adaptive Preprocess → docTR
    # Tier 2a — Adaptive Preprocess → docTR

    from preprocessing import preprocess_for_ocr, AutoAdaptiveConfig

    preprocessed_paths = preprocess_for_ocr(
        path,
        cfg=AutoAdaptiveConfig()
    )

    ocr_input = preprocessed_paths[0] if preprocessed_paths else path

    print(
        f"    [doctr]     {path.name}  "
        f"(preset={AutoAdaptiveConfig().name})"
    )

    doctr_text, doctr_conf = _extract_doctr(
        ocr_input,
        models["ocr"]
    )

    # docTR got almost nothing → straight to Gemini
    if len(doctr_text.strip()) < DOCTR_MIN_CHARS:
        print(f"    [gemini]    {path.name}  (docTR < {DOCTR_MIN_CHARS} chars)")
        gemini_text = (
            _extract_gemini_image(path, models["gemini"]) if is_image
            else _extract_gemini_pdf(path, models["gemini"])
        )
        if len(gemini_text.strip()) >= GEMINI_MIN_CHARS:
            ocr_text, ocr_method = gemini_text, "gemini"
        else:
            ocr_text, ocr_method = doctr_text, "doctr_fallback"

    # docTR confident and the output doesn't look like a garbled read → use it
    elif doctr_conf >= DOCTR_CONF_THRESHOLD and not _looks_like_garbage(doctr_text):
        ocr_text, ocr_method = doctr_text, "doctr"

    # Tier 2b — low confidence, or confidently garbled (e.g. a rotated photo) → escalate to Gemini
    else:
        reason = f"conf {doctr_conf:.3f} < {DOCTR_CONF_THRESHOLD}" if doctr_conf < DOCTR_CONF_THRESHOLD else "output looks garbled"
        print(f"    [gemini]    {path.name}  ({reason})")
        gemini_text = (
            _extract_gemini_image(path, models["gemini"]) if is_image
            else _extract_gemini_pdf(path, models["gemini"])
        )
        if len(gemini_text.strip()) > len(doctr_text.strip()):
            print(f"    [gemini]    won ({len(gemini_text)} > {len(doctr_text)} chars)")
            ocr_text, ocr_method = gemini_text, "gemini"
        else:
            print(f"    [doctr_fb]  Gemini returned less — keeping docTR")
            ocr_text, ocr_method = doctr_text, "doctr_fallback"

    if pymupdf_text is not None:
        # We only reach here because the pymupdf text classified as unknown.
        # Prefer OCR unless it did even worse than the embedded text layer.
        if classify_document(ocr_text) != "unknown" or len(ocr_text.strip()) > len(pymupdf_text.strip()):
            return ocr_text, ocr_method
        print(f"    [pymupdf]   OCR didn't improve on the embedded text layer — keeping pymupdf")
        return pymupdf_text, "pymupdf"

    return ocr_text, ocr_method


# ── Document Type Classifier ──────────────────────────────────────────────────

DOC_TYPE_KEYWORDS: dict[str, list[str]] = {
    "prescription": [
        "rx", "prescribed", "prescription", "tablet", "capsule", "syrup",
        "once daily", "twice daily", "sos", "tab.", "cap.", "mg", "ml", "pharmacy",
    ],
    "discharge_summary": [
        "discharge summary", "discharged", "date of admission", "date of discharge",
        "diagnosis at discharge", "hospital course", "inpatient",
    ],
    "lab_report": [
        "haemoglobin", "hemoglobin", "platelet", "wbc", "rbc", "creatinine",
        "urea", "sodium", "potassium", "glucose", "hba1c", "tsh",
        "liver function", "renal function", "lipid profile", "cbc",
        "complete blood count", "reference range", "normal range",
    ],
    "biopsy_report": [
        "biopsy", "histopathology", "histology", "specimen", "microscopy",
        "gross examination", "microscopic", "section shows", "malignant",
        "benign", "carcinoma", "pathology",
    ],
    "imaging_report": [
        "mri", "ct scan", "x-ray", "ultrasound", "usg", "pet scan",
        "impression:", "findings:", "technique:", "contrast", "radiologist",
    ],
    "operative_notes": [
        "operative notes", "operation notes", "procedure:", "incision",
        "anaesthesia", "anesthesia", "surgeon", "intraoperative", "hemostasis",
    ],
    "insurance": [
        "insurance", "policy number", "claim", "tpa", "mediclaim",
        "pre-authorization", "cashless", "reimbursement",
    ],
    "identity_proof": [
        "aadhaar", "aadhar", "unique identification authority", "uidai",
        "permanent account number", "income tax department", "election commission",
        "voter id", "epic no", "passport no", "republic of india",
        "government of india", "date of birth", "father's name",
    ],
}


def classify_document(text: str) -> str:
    tl     = text.lower()
    scores = {dt: sum(tl.count(kw) for kw in kws) for dt, kws in DOC_TYPE_KEYWORDS.items()}
    best   = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


# ── ID-number patterns ──────────────────────────────────────────────────────
# Reused by admission.py's Tier 1 checks (deterministic, no LLM needed) —
# these are well-defined government ID formats, not fuzzy matching.
_AADHAAR_PAT  = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_PAN_PAT      = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_EPIC_PAT     = re.compile(r"\b[A-Z]{3}\d{7}\b")              # Voter ID (EPIC)
_PASSPORT_PAT = re.compile(r"\b[A-Z][1-9]\d{5}[1-9]\b")       # Indian passport


# ── Field Extraction ──────────────────────────────────────────────────────────

@dataclass
class ExtractedFields:
    doc_type:     str            = "unknown"
    visit_date:   Optional[str] = None
    hospital:     Optional[str] = None
    doctor_name:  Optional[str] = None
    diagnosis:    list           = field(default_factory=list)
    drugs:        list           = field(default_factory=list)
    lab_values:   dict           = field(default_factory=dict)
    surgery_type: Optional[str] = None


_DATE_PATTERNS = [
    r"\b(\d{1,2})[\-/\.](\d{1,2})[\-/\.](\d{2,4})\b",
    r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b",
]
_DRUG_PAT      = re.compile(r"\b(?:tab|cap|inj|syp|syr|susp|oint|gel|drops?)\.?\s+([A-Za-z][\w\-]+(?:\s+\d+\s*mg)?)", re.IGNORECASE)
_DOCTOR_PAT    = re.compile(r"\bDr\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})")
_HOSPITAL_PAT  = re.compile(r"\b([A-Z][\w\s]+(?:Hospital|Medical|Clinic|Centre|Center|Institute)[\w\s]*)\b")
_DIAGNOSIS_PAT = re.compile(r"(?:diagnosis|impression|final diagnosis|assessment)[:\s]+([^\n]{5,120})", re.IGNORECASE)
_LAB_VAL_PAT   = re.compile(r"([A-Za-z][\w\s]{2,30}?)\s*[:\-]\s*([\d\.]+\s*(?:g/dL|mg/dL|mmol/L|U/L|%|lakh|/uL|IU/L)?)")
_SURGERY_PAT   = re.compile(r"(?:procedure|operation|surgery)\s*[:\-]\s*([^\n]{5,80})", re.IGNORECASE)


def extract_fields(text: str, doc_type: str) -> ExtractedFields:
    ef = ExtractedFields(doc_type=doc_type)
    for pat in _DATE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            ef.visit_date = m.group(0).strip()
            break
    m = _DOCTOR_PAT.search(text)
    if m: ef.doctor_name = m.group(1).strip()
    m = _HOSPITAL_PAT.search(text)
    if m: ef.hospital = m.group(1).strip()
    for m in _DIAGNOSIS_PAT.finditer(text):
        d = m.group(1).strip().rstrip(".,;")
        if d and d not in ef.diagnosis:
            ef.diagnosis.append(d)
    if doc_type in {"prescription", "discharge_summary", "operative_notes"}:
        for m in _DRUG_PAT.finditer(text):
            drug = m.group(1).strip()
            if drug not in ef.drugs:
                ef.drugs.append(drug)
    if doc_type == "lab_report":
        for m in _LAB_VAL_PAT.finditer(text):
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            if len(key) > 3 and val:
                ef.lab_values[key] = val
    m = _SURGERY_PAT.search(text)
    if m: ef.surgery_type = m.group(1).strip()
    return ef


# ── Semantic Chunking ─────────────────────────────────────────────────────────

_SECTION_HEADERS = re.compile(
    r"^\s*(?:history|chief complaint|hpi|past medical history|"
    r"diagnosis|impression|discharge diagnosis|"
    r"medications on discharge|discharge medications|medication|drugs given|"
    r"plan|follow.?up|instructions|advice|"
    r"investigations|labs?|reports?|procedure|operation|hospital course"
    r")\s*[:\-]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_LAB_HEADERS = re.compile(
    r"^\s*(?:CBC|complete blood count|liver function|lft|renal function|rft|"
    r"lipid profile|thyroid|blood glucose|urine|coagulation|serology)\s*[:\-]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_SECTION_TO_SEMANTIC: dict[str, str] = {
    "history":                  "patient_information",
    "chief complaint":          "patient_information",
    "hpi":                      "patient_information",
    "past medical history":     "patient_information",
    "diagnosis":                "diagnosis",
    "impression":               "diagnosis",
    "discharge diagnosis":      "diagnosis",
    "medications on discharge": "medication_history",
    "discharge medications":    "medication_history",
    "medication":               "medication_history",
    "drugs given":              "medication_history",
    "plan":                     "follow_up_notes",
    "follow up":                "follow_up_notes",
    "instructions":             "follow_up_notes",
    "advice":                   "follow_up_notes",
    "investigations":           "lab_reports",
    "labs":                     "lab_reports",
    "reports":                  "lab_reports",
    "procedure":                "surgical_history",
    "operation":                "surgical_history",
    "hospital course":          "patient_information",
}

_DOC_TYPE_TO_SEMANTIC: dict[str, str] = {
    "prescription":      "medication_history",
    "discharge_summary": "patient_information",
    "lab_report":        "lab_reports",
    "biopsy_report":     "surgical_history",
    "imaging_report":    "lab_reports",
    "operative_notes":   "surgical_history",
    "insurance":         "patient_information",
    "identity_proof":    "patient_information",
    "unknown":           "patient_information",
}


def _infer_semantic(header: str, doc_type: str) -> str:
    h = header.lower().strip().rstrip(":")
    for key, sem in _SECTION_TO_SEMANTIC.items():
        if key in h:
            return sem
    return _DOC_TYPE_TO_SEMANTIC.get(doc_type, "patient_information")


def _split_on_pattern(text: str, pattern: re.Pattern) -> list[tuple[str, str]]:
    """Returns list of (chunk_text, matched_header)."""
    parts   = pattern.split(text)
    headers = pattern.findall(text)
    if not headers:
        return [(text, "")]
    result = []
    if parts[0].strip():
        result.append((parts[0].strip(), ""))
    for header, body in zip(headers, parts[1:]):
        combined = f"{header.strip()}\n{body.strip()}"
        if combined.strip():
            result.append((combined.strip(), header.strip()))
    return [(c, h) for c, h in result if len(c) > 20]


def _llm_chunk_handwritten(text: str, gemini_client) -> list[tuple[str, str]]:
    """
    Ask Gemini to split handwritten follow-up notes into semantic sections.
    Returns list of (chunk_text, semantic_type) tuples.
    Falls back to a single chunk if Gemini fails.
    """
    prompt = (
        "The following is text from a handwritten Indian hospital follow-up note.\n"
        "Split it into semantic sections. For each section output:\n"
        "SECTION: <one of: patient_information / diagnosis / medication_history / "
        "lab_reports / surgical_history / follow_up_notes>\n"
        "TEXT: <the section text>\n\n"
        "Only output sections in that format, nothing else.\n\n"
        f"NOTE TEXT:\n{text}"
    )
    try:
        resp = gemini_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[{"parts": [{"text": prompt}]}],
        )
        raw          = resp.text.strip()
        chunks       = []
        current_sem  = "follow_up_notes"
        current_lines: list[str] = []
        for line in raw.split("\n"):
            if line.startswith("SECTION:"):
                if current_lines:
                    chunks.append(("\n".join(current_lines).strip(), current_sem))
                current_sem   = line.replace("SECTION:", "").strip()
                current_lines = []
            elif line.startswith("TEXT:"):
                current_lines.append(line.replace("TEXT:", "").strip())
            else:
                current_lines.append(line)
        if current_lines:
            chunks.append(("\n".join(current_lines).strip(), current_sem))
        valid = [(t, s) for t, s in chunks if t.strip()]
        if valid:
            return valid
    except Exception as e:
        print(f"    [LLM chunk] Gemini failed: {e} — using single chunk")
    return [(text.strip(), "follow_up_notes")]


def chunk_document(
    text:              str,
    doc_type:          str,
    models:            dict,
    extraction_method: str = "doctr",
) -> list[tuple[str, str]]:
    """
    Returns list of (chunk_text, semantic_type) tuples.

    Semantic types: patient_information / diagnosis / medication_history /
                    lab_reports / surgical_history / follow_up_notes
    """
    splitter    = models["splitter"]
    default_sem = _DOC_TYPE_TO_SEMANTIC.get(doc_type, "patient_information")

    if doc_type == "prescription":
        return [(text.strip(), "medication_history")]

    if doc_type == "operative_notes":
        return [(text.strip(), "surgical_history")]

    # Handwritten Gemini-extracted notes — use LLM chunking
    if extraction_method == "gemini" and doc_type in {"unknown", "prescription"}:
        print("    [LLM chunk] handwritten note → Gemini semantic splitter")
        return _llm_chunk_handwritten(text, models["gemini"])

    if doc_type == "discharge_summary":
        sections = _split_on_pattern(text, _SECTION_HEADERS)
        if len(sections) > 1:
            result = []
            for sec_text, header in sections:
                sem = _infer_semantic(header, doc_type)
                if len(sec_text) > CHUNK_SIZE * 4:
                    for sub in splitter.split_text(sec_text):
                        result.append((sub, sem))
                else:
                    result.append((sec_text, sem))
            return result

    if doc_type == "lab_report":
        groups = _split_on_pattern(text, _LAB_HEADERS)
        if len(groups) > 1:
            return [(g, "lab_reports") for g, _ in groups]

    if doc_type == "imaging_report":
        findings   = re.search(r"findings[:\s]+(.*?)(?=impression|$)", text, re.IGNORECASE | re.DOTALL)
        impression = re.search(r"impression[:\s]+(.*?)$",              text, re.IGNORECASE | re.DOTALL)
        chunks = []
        if findings:   chunks.append((findings.group(0).strip(),   "lab_reports"))
        if impression: chunks.append((impression.group(0).strip(), "diagnosis"))
        if chunks:     return chunks

    if doc_type == "biopsy_report":
        diag = re.search(r"(?:diagnosis|conclusion)[:\s]+(.*?)$", text, re.IGNORECASE | re.DOTALL)
        if diag:
            return [
                (text[:diag.start()].strip(), "surgical_history"),
                (diag.group(0).strip(),       "diagnosis"),
            ]

    subs = splitter.split_text(text)
    return [(s, default_sem) for s in subs]


# ── Storage ───────────────────────────────────────────────────────────────────

def _stable_id(patient_id: str, file_path: str, chunk_index: int) -> str:
    raw = f"{patient_id}::{file_path}::{chunk_index}"
    return hashlib.md5(raw.encode()).hexdigest()


def _build_records(
    patient_id: str,
    file_path:  Path,
    text:       str,
    method:     str,
    ef:         ExtractedFields,
    models:     dict,
) -> list[dict]:
    chunk_tuples = chunk_document(text, ef.doc_type, models, extraction_method=method)
    records = []
    for i, (chunk_text, semantic_type) in enumerate(chunk_tuples):
        if not chunk_text.strip():
            continue
        meta: dict = {
            "patient_id":        patient_id,
            "file_name":         file_path.name,
            "file_path":         str(file_path),
            "doc_type":          ef.doc_type,
            "semantic_type":     semantic_type,
            "extraction_method": method,
            "chunk_index":       i,
            "total_chunks":      len(chunk_tuples),
            "ingested_at":       datetime.datetime.utcnow().isoformat(),
        }
        if ef.visit_date:   meta["visit_date"]      = ef.visit_date
        if ef.doctor_name:  meta["doctor_name"]     = ef.doctor_name
        if ef.hospital:     meta["hospital"]        = ef.hospital
        if ef.diagnosis:    meta["diagnosis"]       = " | ".join(ef.diagnosis)
        if ef.drugs:        meta["drugs"]           = " | ".join(ef.drugs)
        if ef.surgery_type: meta["surgery_type"]    = ef.surgery_type
        if ef.lab_values:   meta["lab_values_json"] = json.dumps(ef.lab_values)
        records.append({
            "id":       _stable_id(patient_id, str(file_path), i),
            "document": chunk_text,
            "metadata": meta,
        })
    return records


def _embed_and_upsert(records: list[dict], models: dict) -> int:
    if not records:
        return 0
    embedder   = models["embedder"]
    collection = models["collection"]
    prefixed   = [f"Represent this medical document for retrieval: {r['document']}" for r in records]
    embeddings = embedder.encode(
        prefixed,
        batch_size=EMBED_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=len(records) > 10,
    ).tolist()
    collection.upsert(
        ids        = [r["id"]       for r in records],
        documents  = [r["document"] for r in records],
        metadatas  = [r["metadata"] for r in records],
        embeddings = embeddings,
    )
    return len(records)


# ── Public API ────────────────────────────────────────────────────────────────

def ingest_document(patient_id: str, file_path, models: dict) -> dict:
    """
    Full ingestion pipeline for one document.
    Handles PDF, JPG, PNG, TXT automatically.

    Args:
        patient_id : unique patient identifier (string)
        file_path  : path to the document (str or Path)
        models     : dict returned by init()

    Returns dict with status, doc_type, method, chunks, doctor, visit_date, drugs, diagnosis.
    """
    path = Path(file_path)
    print(f"\n── {path.name}  (patient: {patient_id}) ──")

    text, method = extract_text(path, models)
    if not text.strip():
        print("  [SKIP] no text extracted")
        return {"status": "error", "reason": "no text", "file": str(path)}

    print(f"  {len(text):,} chars via {method}")
    doc_type = classify_document(text)
    print(f"  type: {doc_type}")

    ef = extract_fields(text, doc_type)
    print(f"  doctor: {ef.doctor_name}  date: {ef.visit_date}  drugs: {ef.drugs[:2]}")

    records = _build_records(patient_id, path, text, method, ef, models)
    print(f"  {len(records)} chunks")

    stored = _embed_and_upsert(records, models)
    print(f"  stored {stored} → ChromaDB total: {models['collection'].count()}")

    return {
        "status":     "ok",
        "file":       str(path),
        "patient_id": patient_id,
        "doc_type":   doc_type,
        "method":     method,
        "chunks":     stored,
        "doctor":     ef.doctor_name,
        "visit_date": ef.visit_date,
        "drugs":      ef.drugs,
        "diagnosis":  ef.diagnosis,
    }


# ── Retrieval ─────────────────────────────────────────────────────────────────

def build_bm25(patient_id: str, models: dict):
    """Build in-memory BM25 index for a patient. Call after ingestion."""
    from rank_bm25 import BM25Okapi
    collection = models["collection"]
    result     = collection.get(
        where={"patient_id": patient_id},
        include=["documents", "metadatas"],
    )
    docs  = result["documents"]
    metas = result["metadatas"]
    if not docs:
        print(f"  [WARN] No chunks for patient {patient_id}")
        return None, [], []
    tokenized = [_tokenize(d) for d in docs]
    bm25      = BM25Okapi(tokenized)
    print(f"  BM25 built: {len(docs)} chunks for {patient_id}")
    return bm25, docs, metas


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+(?:[a-z]+|[0-9]+)?", text.lower())
    return [t for t in tokens if len(t) > 1]


def vector_search(
    patient_id:           str,
    query:                str,
    models:               dict,
    top_k:                int           = 5,
    doc_type_filter:      Optional[str] = None,
    semantic_type_filter: Optional[str] = None,
) -> list[dict]:
    """
    Vector search scoped to one patient.

    semantic_type_filter options:
        patient_information / diagnosis / medication_history /
        lab_reports / surgical_history / follow_up_notes
    """
    embedder   = models["embedder"]
    collection = models["collection"]

    q_vec = embedder.encode(
        f"Represent this medical document for retrieval: {query}",
        normalize_embeddings=True,
    ).tolist()

    filters = [{"patient_id": patient_id}]
    if doc_type_filter:
        filters.append({"doc_type": doc_type_filter})
    if semantic_type_filter:
        filters.append({"semantic_type": semantic_type_filter})
    where = {"$and": filters} if len(filters) > 1 else filters[0]

    n   = min(top_k, collection.count() or 1)
    res = collection.query(
        query_embeddings=[q_vec],
        n_results=n,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    out = []
    if res["documents"] and res["documents"][0]:
        for text, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            out.append({"text": text, "meta": meta, "score": round(1 - dist, 4)})
    return out


def inspect_all_chunks(patient_id: str, models: dict) -> None:
    """Print all chunks for a patient, grouped by document."""
    collection = models["collection"]
    result     = collection.get(
        where={"patient_id": patient_id},
        include=["documents", "metadatas"],
    )
    if not result["ids"]:
        print("No chunks found.")
        return
    by_file: dict[str, list] = {}
    for text, meta in zip(result["documents"], result["metadatas"]):
        fname = meta.get("file_name", "unknown")
        by_file.setdefault(fname, []).append((text, meta))
    total = sum(len(v) for v in by_file.values())
    print(f"Patient: {patient_id}  |  {len(by_file)} docs  |  {total} chunks\n")
    for fname, chunks in sorted(by_file.items()):
        m0 = chunks[0][1]
        print(f"  {fname}")
        print(f"    doc_type={m0.get('doc_type')}  method={m0.get('extraction_method')}  "
              f"date={m0.get('visit_date')}  chunks={len(chunks)}")
        sem_counts: dict[str, int] = {}
        for _, cm in chunks:
            s = cm.get("semantic_type", "unknown")
            sem_counts[s] = sem_counts.get(s, 0) + 1
        print(f"    semantic types: {sem_counts}")
        if m0.get("drugs"):     print(f"    drugs:     {m0['drugs']}")
        if m0.get("diagnosis"): print(f"    diagnosis: {m0['diagnosis']}")
        print()
