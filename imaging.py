"""
TheArch — Imaging Pipeline
==========================
Handles raw medical scan *images* (X-ray, CT, MRI, ultrasound pixel data).
This is distinct from ingestion.py which handles text-based imaging *reports*.

Pipeline:
    1. Detect scan modality from filename / parent directory
    2. Gemini 2.5 Flash Vision → structured clinical description
    3. Chest X-ray only: BioViL-T zero-shot phrase scoring → abnormality flags
    4. Merge descriptions; flag any ABNORMAL findings
    5. Store as doc_type=imaging_scan in ChromaDB via shared ingestion helpers

Usage:
    from imaging import load_imaging_models, ingest_scan
    imaging_models = load_imaging_models()
    result = ingest_scan(patient_id, path, models, imaging_models)
    # models is the dict returned by ingestion.init()
"""

import re
import base64
import io
import hashlib
import datetime
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────

GEMINI_MODEL              = "gemini-2.5-flash"
BIOVILT_MODEL_ID          = "microsoft/BiomedVLP-BioViL-T"
BIOVILT_ABNORMAL_THRESHOLD = 0.22    # phrase similarity above this = likely present
EMBED_BATCH_SIZE           = 32
EMBED_PREFIX               = "Represent this medical document for retrieval: "

# BioViL-T is only meaningful for chest X-rays
CHEST_PATHOLOGY_PHRASES: list[str] = [
    "no acute cardiopulmonary abnormality",
    "normal chest radiograph",
    "pneumonia with consolidation",
    "lobar consolidation",
    "pleural effusion",
    "pneumothorax",
    "tension pneumothorax",
    "cardiomegaly",
    "pulmonary edema",
    "pulmonary nodule",
    "pulmonary mass",
    "atelectasis",
    "emphysema",
    "interstitial lung disease",
    "mediastinal widening",
    "pleural thickening",
    "rib fracture",
    "lung hyperinflation",
    "hilar lymphadenopathy",
    "air space opacity",
    "reticulonodular pattern",
    "cavitary lesion",
]

_NORMAL_PHRASES = {
    "no acute cardiopulmonary abnormality",
    "normal chest radiograph",
}

# ── Modality detection ─────────────────────────────────────────────────────────

_MODALITY_PATTERNS: list[tuple] = [
    (re.compile(r"\b(?:chest|cxr|xray|x[\-_\s]ray)\b",       re.I), "chest_xray"),
    (re.compile(r"\b(?:ct|computed[\-_]tomography|ctscan)\b", re.I), "ct_scan"),
    (re.compile(r"\b(?:mri|magnetic[\-_]resonance|flair|dwi)\b", re.I), "mri"),
    (re.compile(r"\b(?:usg|ultrasound|sonography|sono)\b",    re.I), "ultrasound"),
    (re.compile(r"\b(?:pet|positron)\b",                       re.I), "pet_scan"),
    (re.compile(r"\b(?:mammo|mammogram|mammography)\b",        re.I), "mammogram"),
    (re.compile(r"\b(?:dexa|bone[\-_]density)\b",              re.I), "bone_density"),
]


def detect_modality(path: Path) -> str:
    """Infer scan modality from filename and parent directory name."""
    search_text = f"{path.stem} {path.parent.name}"
    for pattern, modality in _MODALITY_PATTERNS:
        if pattern.search(search_text):
            return modality
    return "unknown_scan"


# ── Per-modality Gemini prompts ────────────────────────────────────────────────

_SCAN_PROMPTS: dict[str, str] = {
    "chest_xray": (
        "This is a chest X-ray (CXR) image from an Indian hospital. "
        "Provide a structured clinical description with these sections:\n"
        "TECHNICAL: (PA/AP/lateral, rotation, inspiratory effort)\n"
        "CARDIAC: (size, silhouette, mediastinum)\n"
        "LUNGS: (any opacities, consolidation, effusion, pneumothorax, masses, vasculature)\n"
        "BONES: (ribs, clavicles, spine — any fractures or deformities)\n"
        "SOFT TISSUES: (diaphragm, subdiaphragmatic area)\n"
        "IMPRESSION: (key findings in 1-3 sentences)\n\n"
        "For any finding that appears abnormal, write 'ABNORMAL:' before describing it. "
        "Describe only — do not diagnose or recommend treatment."
    ),
    "ct_scan": (
        "This is a CT scan image from an Indian hospital. "
        "Describe: body region visible, slice plane, visible organs and their appearance, "
        "any masses, densities, calcifications, fluid collections, or structural changes. "
        "Write 'ABNORMAL:' before any finding that appears pathological. "
        "Describe only — do not diagnose."
    ),
    "mri": (
        "This is an MRI image from an Indian hospital. "
        "Describe: body region, MRI sequence type if discernible (T1/T2/FLAIR/DWI/GRE), "
        "signal characteristics of visible structures, any focal lesions, "
        "signal abnormalities, mass effect, or structural asymmetry. "
        "Write 'ABNORMAL:' before any pathological finding. "
        "Describe only — do not diagnose."
    ),
    "ultrasound": (
        "This is an ultrasound image from an Indian hospital. "
        "Describe: organ being imaged, echogenicity, any masses, cysts, fluid collections, "
        "wall thickening, ductal dilatation, vascular findings, visible measurements. "
        "Write 'ABNORMAL:' before any pathological finding. "
        "Describe only — do not diagnose."
    ),
    "pet_scan": (
        "This is a PET or PET-CT scan image from an Indian hospital. "
        "Describe: body region, any areas of increased uptake/hypermetabolism, "
        "distribution pattern, and anatomic landmarks visible. "
        "Write 'ABNORMAL:' before any suspicious finding. "
        "Describe only — do not diagnose."
    ),
    "mammogram": (
        "This is a mammogram from an Indian hospital. "
        "Describe: breast density (if assessable), any masses, calcifications, "
        "architectural distortion, asymmetries, or skin/nipple changes. "
        "Write 'ABNORMAL:' before any suspicious finding. "
        "Describe only — do not diagnose."
    ),
}

_DEFAULT_SCAN_PROMPT = (
    "This is a medical imaging study from an Indian hospital. "
    "Describe what is visible: body region, visible structures, and any apparent abnormalities. "
    "Write 'ABNORMAL:' before any pathological finding. "
    "Describe only — do not diagnose."
)


# ── BioViL-T loading ───────────────────────────────────────────────────────────

def load_imaging_models() -> dict:
    """
    Load imaging-specific models.  BioViL-T is optional — if hi-ml-multimodal
    is not installed the pipeline falls back to Gemini Vision only.

    Returns dict with keys:
        "biovilt_engine": ImageTextInferenceEngine or None
        "biovilt_available": bool
    """
    result = {"biovilt_engine": None, "biovilt_available": False}
    try:
        from health_multimodal.image import get_biovil_t_image_encoder
        from health_multimodal.text  import get_bert_inference
        from health_multimodal.vlp   import ImageTextInferenceEngine
        print("Loading BioViL-T (chest X-ray secondary check)...")
        engine = ImageTextInferenceEngine(
            image_inference=get_biovil_t_image_encoder(),
            text_inference=get_bert_inference(),
        )
        result["biovilt_engine"]    = engine
        result["biovilt_available"] = True
        print("  BioViL-T OK")
    except ImportError:
        print("  BioViL-T not available (hi-ml-multimodal not installed) — Gemini Vision only")
    except Exception as e:
        print(f"  BioViL-T load failed: {e} — Gemini Vision only")
    return result


# ── Image helpers ──────────────────────────────────────────────────────────────

def _img_to_b64(path: Path) -> str:
    from PIL import Image as PILImage
    img = PILImage.open(str(path)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── Gemini Vision description ──────────────────────────────────────────────────

def describe_scan_gemini(path: Path, modality: str, gemini_client) -> str:
    """
    Send the scan image to Gemini Vision and return a structured clinical description.
    Returns empty string on failure.
    """
    import time
    prompt = _SCAN_PROMPTS.get(modality, _DEFAULT_SCAN_PROMPT)
    b64    = _img_to_b64(path)
    for attempt in range(3):
        try:
            resp = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"parts": [
                    {"inline_data": {"mime_type": "image/png", "data": b64}},
                    {"text": prompt},
                ]}],
            )
            return resp.text.strip()
        except Exception as e:
            if attempt < 2:
                time.sleep((attempt + 1) * 10)
            else:
                print(f"  [WARN] Gemini Vision failed for {path.name}: {e}")
    return ""


# ── BioViL-T chest X-ray scoring ──────────────────────────────────────────────

def check_chest_xray_biovilt(path: Path, imaging_models: dict) -> dict:
    """
    Score the chest X-ray against each pathology phrase using BioViL-T.
    Returns {phrase: similarity_score}.  Empty dict if BioViL-T unavailable.
    """
    if not imaging_models.get("biovilt_available"):
        return {}
    engine = imaging_models["biovilt_engine"]
    scores: dict[str, float] = {}
    for phrase in CHEST_PATHOLOGY_PHRASES:
        try:
            score = engine.get_similarity_score_from_raw_data(
                image_path=path,
                query_text=phrase,
            )
            scores[phrase] = round(float(score), 4)
        except Exception:
            pass
    return scores


def _get_abnormal_flags(biovil_scores: dict) -> list[str]:
    """Return phrases above threshold, excluding 'normal' catch-all phrases."""
    return [
        phrase for phrase, score in biovil_scores.items()
        if score >= BIOVILT_ABNORMAL_THRESHOLD and phrase not in _NORMAL_PHRASES
    ]


# ── Storage helpers ────────────────────────────────────────────────────────────

def _stable_id(patient_id: str, file_path: str, chunk_index: int) -> str:
    raw = f"scan::{patient_id}::{file_path}::{chunk_index}"
    return hashlib.md5(raw.encode()).hexdigest()


def _embed_and_upsert_scan(records: list[dict], models: dict) -> int:
    if not records:
        return 0
    embedder   = models["embedder"]
    collection = models["collection"]
    prefixed   = [f"{EMBED_PREFIX}{r['document']}" for r in records]
    embeddings = embedder.encode(
        prefixed,
        batch_size=EMBED_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).tolist()
    collection.upsert(
        ids        = [r["id"]       for r in records],
        documents  = [r["document"] for r in records],
        metadatas  = [r["metadata"] for r in records],
        embeddings = embeddings,
    )
    return len(records)


# ── Public API ─────────────────────────────────────────────────────────────────

def ingest_scan(
    patient_id:     str,
    path:           Path,
    models:         dict,
    imaging_models: dict,
) -> dict:
    """
    Full imaging ingestion pipeline for one scan image.

    Args:
        patient_id:     unique patient identifier
        path:           path to the image file (jpg/png/bmp)
        models:         dict returned by ingestion.init()
        imaging_models: dict returned by load_imaging_models()

    Returns dict: {status, file, patient_id, modality, chunks,
                   abnormal_flags, biovilt_scores, gemini_description}
    """
    path = Path(path)
    print(f"\n── [SCAN] {path.name}  (patient: {patient_id}) ──")

    modality = detect_modality(path)
    print(f"  modality: {modality}")

    # ── Gemini Vision ──────────────────────────────────────────────────────────
    print(f"  [gemini-vision] describing scan...")
    gemini_desc = describe_scan_gemini(path, modality, models["gemini"])
    if not gemini_desc:
        print("  [SKIP] Gemini Vision returned no description")
        return {"status": "error", "reason": "gemini vision returned empty", "file": str(path)}
    print(f"  gemini_desc: {len(gemini_desc)} chars")

    # ── BioViL-T (chest X-ray only) ───────────────────────────────────────────
    biovil_scores:  dict[str, float] = {}
    abnormal_flags: list[str]        = []
    biovil_summary = ""

    if modality == "chest_xray" and imaging_models.get("biovilt_available"):
        print("  [biovilt] scoring pathology phrases...")
        biovil_scores  = check_chest_xray_biovilt(path, imaging_models)
        abnormal_flags = _get_abnormal_flags(biovil_scores)
        if abnormal_flags:
            biovil_summary = (
                "\n\nBioViL-T secondary check flagged the following findings "
                f"(score ≥ {BIOVILT_ABNORMAL_THRESHOLD}):\n"
                + "\n".join(f"  • {f} ({biovil_scores[f]:.3f})" for f in abnormal_flags)
            )
            print(f"  biovilt flags: {abnormal_flags}")
        else:
            # Check if 'normal' phrases are high — likely a normal CXR
            normal_scores = {p: biovil_scores.get(p, 0) for p in _NORMAL_PHRASES if p in biovil_scores}
            if normal_scores:
                top_normal = max(normal_scores, key=normal_scores.get)
                biovil_summary = (
                    f"\n\nBioViL-T secondary check: highest normal-phrase score was "
                    f'"{top_normal}" ({normal_scores[top_normal]:.3f}) — '
                    "no specific pathology phrases exceeded the abnormal threshold."
                )
            print("  biovilt: no abnormal flags")

    # ── Build combined document text ───────────────────────────────────────────
    combined_text = gemini_desc
    if biovil_summary:
        combined_text += biovil_summary

    is_abnormal = bool(abnormal_flags) or bool(re.search(r"\bABNORMAL\b", gemini_desc))

    # ── Build ChromaDB record ──────────────────────────────────────────────────
    meta: dict = {
        "patient_id":        patient_id,
        "file_name":         path.name,
        "file_path":         str(path),
        "doc_type":          "imaging_scan",
        "semantic_type":     "lab_reports",   # scans map to lab_reports for retrieval
        "extraction_method": "gemini_vision",
        "modality":          modality,
        "is_abnormal":       str(is_abnormal).lower(),
        "chunk_index":       0,
        "total_chunks":      1,
        "ingested_at":       datetime.datetime.utcnow().isoformat(),
    }
    if abnormal_flags:
        meta["abnormal_flags"] = " | ".join(abnormal_flags)

    record = {
        "id":       _stable_id(patient_id, str(path), 0),
        "document": combined_text,
        "metadata": meta,
    }

    stored = _embed_and_upsert_scan([record], models)
    print(f"  stored {stored} chunk → ChromaDB total: {models['collection'].count()}")

    return {
        "status":              "ok",
        "file":                str(path),
        "patient_id":          patient_id,
        "modality":            modality,
        "chunks":              stored,
        "abnormal_flags":      abnormal_flags,
        "biovilt_scores":      biovil_scores,
        "gemini_description":  gemini_desc,
        "is_abnormal":         is_abnormal,
    }
