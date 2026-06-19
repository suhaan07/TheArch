"""
HeyDoc — OCR Evaluation Pipeline  (v5)
=======================================
Evaluates the confidence-aware preprocessing pipeline introduced in v5.

Key changes vs v4
-----------------
  • evaluate_confidence_aware()   — the primary evaluation function.
    Runs Stage-1 OCR, selects arms based on confidence band, runs OCR on all
    arms, picks the winner, and reports arm-by-arm metrics.

  • ArmReport dataclass           — per-arm metrics (conf, char_count, delta).

  • ConfidenceAwareReport         — top-level report with baseline, winner,
    all arms, band, and the full BestCandidate object.

  • evaluate_ocr_improvement()    — v4 API preserved for backward compatibility.
    Now calls the confidence-aware path internally when ocr_fn is supplied.

  • evaluate_all_presets()        — still available for ablation / comparison.

Public API
----------
    evaluate_confidence_aware(path, models)   → ConfidenceAwareReport
    evaluate_ocr_improvement(path, models, cfg=None)  → OcrReport  (v4 compat)
    evaluate_all_presets(path, models)        → list[OcrReport]
    recommend_best_preset(reports)            → OcrReport
    print_confidence_aware_report(report)
    print_report(report)
    print_comparison_table(reports)
    export_csv(reports, out_path)
    plot_comparison_chart(reports, out_path)
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("heydoc.ocr_evaluation")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

REPORT_DIR = Path("ocr_reports")
VISUAL_DIR = REPORT_DIR / "visuals"
REPORT_DIR.mkdir(exist_ok=True)
VISUAL_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# REPORT DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ArmReport:
    """Metrics for one preprocessing arm."""
    arm_name:        str
    confidence:      float
    char_count:      int
    conf_delta:      float    # vs original baseline
    char_delta_pct:  float    # vs original baseline
    is_winner:       bool = False


@dataclass
class ConfidenceAwareReport:
    """
    Full report produced by evaluate_confidence_aware().
    Contains per-arm breakdown and the chosen winner.
    """
    file_name:       str
    evaluated_at:    str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())

    # Stage-1 baseline
    baseline_conf:   float = 0.0
    baseline_chars:  int   = 0
    conf_band:       str   = ""       # "high" | "medium_high" | "medium" | "low"

    # Winner
    winner_arm:      str   = ""
    winner_conf:     float = 0.0
    winner_chars:    int   = 0
    winner_text_sample: str = ""

    # Geometry
    skew_angle:      float = 0.0
    occupancy_ratio: float = 1.0
    document_tier:   str   = ""

    # All arm results
    arms:            list[ArmReport] = field(default_factory=list)

    # Artefact paths
    visual_path:     str = ""
    report_path:     str = ""

    def conf_improvement(self) -> float:
        return round(self.winner_conf - self.baseline_conf, 4)

    def is_improved(self) -> bool:
        return self.conf_improvement() > 0.0

    def summary(self) -> dict:
        return {
            "file":             self.file_name,
            "conf_band":        self.conf_band,
            "baseline_conf":    round(self.baseline_conf, 4),
            "winner_arm":       self.winner_arm,
            "winner_conf":      round(self.winner_conf, 4),
            "conf_improvement": self.conf_improvement(),
            "is_improved":      self.is_improved(),
            "skew_angle":       round(self.skew_angle, 2),
            "occupancy_ratio":  round(self.occupancy_ratio, 4),
            "document_tier":    self.document_tier,
            "arms_evaluated":   len(self.arms),
        }


@dataclass
class OcrReport:
    """v4-compatible report — preserved for backward compatibility."""
    file_name:              str
    preset_name:            str   = "unknown"
    evaluated_at:           str   = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    before_chars:           int   = 0
    before_words:           int   = 0
    before_confidence:      float = 0.0
    before_text_sample:     str   = ""
    after_chars:            int   = 0
    after_words:            int   = 0
    after_confidence:       float = 0.0
    after_text_sample:      str   = ""
    char_improvement_pct:   float = 0.0
    word_improvement_pct:   float = 0.0
    confidence_delta:       float = 0.0
    skew_before:            float = 0.0
    skew_after:             float = 0.0
    occupancy_before:       float = 1.0
    occupancy_after:        float = 1.0
    blur_before:            float = 0.0
    blur_after:             float = 0.0
    document_tier:          str   = ""
    recommended_preset:     str   = ""
    visual_path:            str   = ""
    report_path:            str   = ""

    def quality_report(self) -> dict:
        return {
            "before_characters":    self.before_chars,
            "after_characters":     self.after_chars,
            "before_words":         self.before_words,
            "after_words":          self.after_words,
            "before_confidence":    round(self.before_confidence, 4),
            "after_confidence":     round(self.after_confidence, 4),
            "char_improvement_pct": round(self.char_improvement_pct, 2),
            "word_improvement_pct": round(self.word_improvement_pct, 2),
            "confidence_delta":     round(self.confidence_delta, 4),
            "text_length_ratio":    round(
                self.after_chars / self.before_chars, 4
            ) if self.before_chars > 0 else 0.0,
            "skew_before":          round(self.skew_before, 2),
            "skew_after":           round(self.skew_after, 2),
            "occupancy_before":     round(self.occupancy_before, 4),
            "occupancy_after":      round(self.occupancy_after, 4),
            "blur_before":          round(self.blur_before, 2),
            "blur_after":           round(self.blur_after, 2),
            "preset_used":          self.preset_name,
            "document_tier":        self.document_tier,
        }

    def composite_score(self) -> float:
        return (
            0.55 * self.confidence_delta
            + 0.30 * (self.char_improvement_pct / 100.0)
            + 0.15 * (self.word_improvement_pct / 100.0)
        )


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _count_words(text: str) -> int:
    return len(text.split()) if text.strip() else 0


def _pct_change(before: float, after: float) -> float:
    if before == 0:
        return 100.0 if after > 0 else 0.0
    return round((after - before) / before * 100, 2)


def _run_doctr(path: Path, ocr_model) -> tuple[str, float]:
    try:
        from doctr.io import DocumentFile
        doc_input = (DocumentFile.from_pdf(str(path))
                     if path.suffix.lower() == ".pdf"
                     else DocumentFile.from_images([str(path)]))
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
    except Exception as exc:
        logger.error("docTR failed: %s", exc)
        return "", 0.0


def _run_doctr_on_array(gray: np.ndarray, ocr_model) -> tuple[str, float]:
    """
    Run docTR directly on a numpy grayscale array without writing to disk first.
    Used inside the confidence-aware pipeline to avoid redundant file I/O.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        cv2.imwrite(str(tmp_path), gray)
        return _run_doctr(tmp_path, ocr_model)
    finally:
        tmp_path.unlink(missing_ok=True)


def _rasterise_first_page(path: Path, dpi: int = 150) -> Optional[np.ndarray]:
    try:
        if path.suffix.lower() == ".pdf":
            import fitz
            doc = fitz.open(str(path))
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = doc[0].get_pixmap(matrix=mat)
            doc.close()
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            if pix.n == 4:
                return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            if pix.n == 1:
                return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            return arr
        return cv2.imread(str(path))
    except Exception as exc:
        logger.warning("rasterise failed for %s: %s", path.name, exc)
        return None


def _build_visual_confidence_aware(
    original_bgr:  np.ndarray,
    report:        ConfidenceAwareReport,
    uid:           str,
) -> str:
    """
    Side-by-side visual: original | winner.
    Annotated with confidence band, arm results, and winner flag.
    """
    from preprocessing import PREPROCESSED_DIR

    TH = 700

    def _rh(img: np.ndarray) -> np.ndarray:
        r = TH / img.shape[0]
        return cv2.resize(img, (int(img.shape[1] * r), TH))

    orig = original_bgr if len(original_bgr.shape) == 3 else cv2.cvtColor(original_bgr, cv2.COLOR_GRAY2BGR)
    orig = _rh(orig)

    winner_path = PREPROCESSED_DIR / f"{Path(report.file_name).stem}_{report.winner_arm}.png"
    if winner_path.exists():
        win_img = cv2.imread(str(winner_path))
        if win_img is not None:
            if len(win_img.shape) == 2:
                win_img = cv2.cvtColor(win_img, cv2.COLOR_GRAY2BGR)
            win_img = _rh(win_img)
        else:
            win_img = np.full((TH, 500, 3), 180, np.uint8)
    else:
        win_img = np.full((TH, 500, 3), 180, np.uint8)

    BAR   = 130
    FONT  = cv2.FONT_HERSHEY_SIMPLEX
    FS    = 0.44
    WHITE = (255, 255, 255)
    GREEN = (60, 210, 60)
    GOLD  = (30, 200, 230)
    BG    = (25, 25, 25)

    def _bar(panel, lines, col):
        b = np.full((BAR, panel.shape[1], 3), BG, dtype=np.uint8)
        for i, ln in enumerate(lines[:6]):
            cv2.putText(b, ln, (6, 18 + i * 19), FONT, FS, col, 1, cv2.LINE_AA)
        return np.vstack([b, panel])

    arm_lines = [f"  {a.arm_name:<24} conf={a.confidence:.4f}  Δ={a.conf_delta:+.4f}"
                 + (" ◀ WINNER" if a.is_winner else "")
                 for a in report.arms]

    before_lines = [
        f"ORIGINAL  band={report.conf_band}",
        f"conf={report.baseline_conf:.4f}   chars={report.baseline_chars}",
        f"skew={report.skew_angle:+.1f}°  occ={report.occupancy_ratio:.2f}",
        f"tier={report.document_tier}",
    ] + arm_lines[:3]

    after_lines = [
        f"WINNER  arm={report.winner_arm}",
        f"conf={report.winner_conf:.4f}   chars={report.winner_chars}",
        f"Δconf={report.conf_improvement():+.4f}",
        f"{'IMPROVED ✓' if report.is_improved() else 'NO IMPROVEMENT — original kept'}",
    ]

    orig_p  = _bar(orig,    before_lines, WHITE)
    win_p   = _bar(win_img, after_lines,  GREEN if report.is_improved() else GOLD)
    max_h   = max(orig_p.shape[0], win_p.shape[0])

    def _pad(img, th):
        if img.shape[0] < th:
            p = np.full((th - img.shape[0], img.shape[1], 3), BG, dtype=np.uint8)
            return np.vstack([img, p])
        return img

    orig_p   = _pad(orig_p, max_h)
    win_p    = _pad(win_p,  max_h)
    div      = np.full((max_h, 3, 3), (0, 100, 255), dtype=np.uint8)
    combined = np.hstack([orig_p, div, win_p])

    out = VISUAL_DIR / f"{Path(report.file_name).stem}_{uid}_confidence_aware.png"
    cv2.imwrite(str(out), combined)
    logger.info("  visual → %s", out.name)
    return str(out)


# ══════════════════════════════════════════════════════════════════════════════
# PRIMARY API — CONFIDENCE-AWARE EVALUATION
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_confidence_aware(
    path,
    models:      dict,
    save_report: bool = True,
) -> ConfidenceAwareReport:
    """
    Run the v5 confidence-aware preprocessing pipeline and return full metrics.

    This is the PRIMARY evaluation function for v5.

    Architecture:
        Stage 1  docTR on original  → baseline confidence
        Stage 2  Select arms based on confidence band + geometry
        Stage 3  docTR on each arm
        Stage 4  Winner = highest confidence arm
                 (original is always a candidate — quality never degrades)

    Args:
        path:        Document path (PDF, JPG, PNG, TIFF, BMP).
        models:      Dict with "ocr" key (docTR predictor).
        save_report: Write JSON to ocr_reports/.

    Returns:
        ConfidenceAwareReport
    """
    from preprocessing import (
        confidence_aware_preprocess,
        assess_document_quality,
        _rasterise_pdf,
    )

    path      = Path(path)
    uid       = uuid.uuid4().hex[:8]
    suffix    = path.suffix.lower()
    ocr_model = models.get("ocr")
    report    = ConfidenceAwareReport(file_name=path.name)

    # ── Load first page as BGR ─────────────────────────────────────────────────
    if suffix == ".pdf":
        pages = _rasterise_pdf(path)
        bgr   = pages[0] if pages else None
    else:
        bgr = cv2.imread(str(path))

    if bgr is None:
        logger.error("evaluate_confidence_aware: cannot load %s", path.name)
        return report

    # ── ocr_fn wrapper for confidence_aware_preprocess ────────────────────────
    def ocr_fn(gray: np.ndarray) -> tuple[str, float]:
        return _run_doctr_on_array(gray, ocr_model)

    # ── Run confidence-aware pipeline ─────────────────────────────────────────
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    quality = assess_document_quality(gray)

    result = confidence_aware_preprocess(
        bgr     = bgr,
        ocr_fn  = ocr_fn,
        stem    = path.stem,
        quality = quality,
    )

    # ── Populate report ───────────────────────────────────────────────────────
    report.baseline_conf   = result.baseline_conf
    report.baseline_chars  = result.baseline.char_count
    report.conf_band       = result.conf_band
    report.winner_arm      = result.winner.arm_name
    report.winner_conf     = result.winner.confidence
    report.winner_chars    = result.winner.char_count
    report.winner_text_sample = result.winner.text[:200]
    report.skew_angle      = result.skew_angle
    report.occupancy_ratio = result.occupancy_ratio
    report.document_tier   = result.quality.tier.name

    # Per-arm breakdown
    for c in result.all_candidates:
        report.arms.append(ArmReport(
            arm_name       = c.arm_name,
            confidence     = c.confidence,
            char_count     = c.char_count,
            conf_delta     = round(c.confidence - result.baseline_conf, 4),
            char_delta_pct = _pct_change(result.baseline.char_count, c.char_count),
            is_winner      = (c.arm_name == result.winner.arm_name),
        ))

    # ── Visual ────────────────────────────────────────────────────────────────
    report.visual_path = _build_visual_confidence_aware(bgr, report, uid)

    # ── JSON save ─────────────────────────────────────────────────────────────
    if save_report:
        data = {
            **report.summary(),
            "arms": [
                {
                    "arm_name":       a.arm_name,
                    "confidence":     round(a.confidence, 4),
                    "char_count":     a.char_count,
                    "conf_delta":     round(a.conf_delta, 4),
                    "char_delta_pct": round(a.char_delta_pct, 2),
                    "is_winner":      a.is_winner,
                }
                for a in report.arms
            ],
            "winner_text_sample": report.winner_text_sample,
            "visual_path":        report.visual_path,
            "evaluated_at":       report.evaluated_at,
        }
        rp = REPORT_DIR / f"{path.stem}_{uid}_confidence_aware.json"
        rp.write_text(json.dumps(data, indent=2))
        report.report_path = str(rp)

    return report


# ══════════════════════════════════════════════════════════════════════════════
# CONSOLE OUTPUT — CONFIDENCE-AWARE
# ══════════════════════════════════════════════════════════════════════════════

def print_confidence_aware_report(report: ConfidenceAwareReport) -> None:
    width = 72
    print(f"\n{'='*width}")
    print(f"  Confidence-Aware OCR Report — {report.file_name}")
    print(f"  Tier: {report.document_tier}   Band: {report.conf_band}")
    print(f"{'='*width}")
    print(f"  {'Stage 1 baseline conf':<38} {report.baseline_conf:.4f}  ({report.baseline_chars} chars)")
    print(f"  {'Winner arm':<38} {report.winner_arm}")
    print(f"  {'Winner conf':<38} {report.winner_conf:.4f}  ({report.winner_chars} chars)")
    delta = report.conf_improvement()
    marker = "✓ IMPROVED" if delta > 0 else "— no improvement (original kept)"
    print(f"  {'Confidence delta':<38} {delta:+.4f}  {marker}")
    print(f"  {'Skew':<38} {report.skew_angle:+.1f}°")
    print(f"  {'Occupancy':<38} {report.occupancy_ratio:.3f}")
    print(f"\n  {'Arm':<28} {'Conf':>8} {'ΔConf':>9} {'Chars':>7} {'ΔChars%':>9}  Winner?")
    print(f"  {'-'*68}")
    for a in sorted(report.arms, key=lambda x: x.confidence, reverse=True):
        w = "◀ YES" if a.is_winner else ""
        print(
            f"  {a.arm_name:<28} {a.confidence:>8.4f} {a.conf_delta:>+8.4f} "
            f"{a.char_count:>7} {a.char_delta_pct:>+8.1f}%  {w}"
        )
    if report.visual_path:
        print(f"\n  Visual:  {report.visual_path}")
    if report.report_path:
        print(f"  JSON:    {report.report_path}")
    print(f"{'='*width}\n")


def export_confidence_aware_csv(
    reports:  list[ConfidenceAwareReport],
    out_path: Path,
) -> None:
    out_path   = Path(out_path)
    fieldnames = [
        "file_name", "conf_band", "document_tier",
        "baseline_conf", "baseline_chars",
        "winner_arm", "winner_conf", "winner_chars",
        "conf_improvement", "is_improved",
        "skew_angle", "occupancy_ratio",
        "arms_evaluated",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in reports:
            s = r.summary()
            writer.writerow({k: s.get(k, "") for k in fieldnames})


# ══════════════════════════════════════════════════════════════════════════════
# v4-COMPATIBLE API (preserved for backward compatibility)
# ══════════════════════════════════════════════════════════════════════════════

def _build_visual(
    original_path:  Path,
    processed_path: Path,
    report:         OcrReport,
    uid:            str,
) -> str:
    orig = _rasterise_first_page(original_path)
    proc = cv2.imread(str(processed_path)) if processed_path.exists() else None
    if orig is None and proc is None:
        return ""

    TH = 700

    def _rh(img):
        r = TH / img.shape[0]
        return cv2.resize(img, (int(img.shape[1] * r), TH))

    orig = _rh(orig) if orig is not None else np.full((TH, 500, 3), 200, np.uint8)
    if proc is not None:
        if len(proc.shape) == 2:
            proc = cv2.cvtColor(proc, cv2.COLOR_GRAY2BGR)
        proc = _rh(proc)
    else:
        proc = np.full((TH, 500, 3), 200, np.uint8)

    BAR, FONT, FS = 100, cv2.FONT_HERSHEY_SIMPLEX, 0.48
    WHITE = (255, 255, 255)
    GREEN = (60, 210, 60)
    RED   = (60, 60, 220)
    BG    = (25, 25, 25)

    def _bar(panel, lines, col):
        b = np.full((BAR, panel.shape[1], 3), BG, dtype=np.uint8)
        for i, ln in enumerate(lines[:5]):
            cv2.putText(b, ln, (6, 18 + i * 18), FONT, FS, col, 1, cv2.LINE_AA)
        return np.vstack([b, panel])

    delta_col    = GREEN if report.char_improvement_pct >= 0 else RED
    before_lines = [
        "BEFORE preprocessing",
        f"chars={report.before_chars}   words={report.before_words}",
        f"docTR conf={report.before_confidence:.3f}",
        f"skew={report.skew_before:+.1f}°   occ={report.occupancy_before:.2f}   blur={report.blur_before:.0f}",
    ]
    after_lines  = [
        f"AFTER  [{report.preset_name}]",
        f"chars={report.after_chars}   words={report.after_words}",
        f"docTR conf={report.after_confidence:.3f}   Δchars={report.char_improvement_pct:+.1f}%",
        f"skew={report.skew_after:+.1f}°   occ={report.occupancy_after:.2f}   blur={report.blur_after:.0f}",
    ]

    orig_p = _bar(orig, before_lines, WHITE)
    proc_p = _bar(proc, after_lines,  delta_col)
    max_h  = max(orig_p.shape[0], proc_p.shape[0])

    def _pad(img, th):
        if img.shape[0] < th:
            p = np.full((th - img.shape[0], img.shape[1], 3), BG, dtype=np.uint8)
            return np.vstack([img, p])
        return img

    orig_p   = _pad(orig_p, max_h)
    proc_p   = _pad(proc_p, max_h)
    div      = np.full((max_h, 3, 3), (0, 100, 255), dtype=np.uint8)
    combined = np.hstack([orig_p, div, proc_p])

    out = VISUAL_DIR / f"{original_path.stem}_{uid}_{report.preset_name}.png"
    cv2.imwrite(str(out), combined)
    return str(out)


def evaluate_ocr_improvement(
    path,
    models:      dict,
    cfg=None,
    save_report: bool = True,
) -> OcrReport:
    """
    v4-compatible evaluation. Preserved for backward compatibility.
    For new code, prefer evaluate_confidence_aware().
    """
    from preprocessing import (
        preprocess_for_ocr, AutoAdaptiveConfig,
        assess_document_quality, select_preset,
        _detect_skew, _detect_document_boundary, detect_blur,
    )

    path      = Path(path)
    uid       = uuid.uuid4().hex[:8]
    cfg       = cfg or AutoAdaptiveConfig()
    report    = OcrReport(file_name=path.name, preset_name=cfg.name)
    ocr_model = models.get("ocr")

    orig_gray = None
    try:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            import fitz
            doc  = fitz.open(str(path))
            mat  = fitz.Matrix(150 / 72, 150 / 72)
            pix  = doc[0].get_pixmap(matrix=mat)
            doc.close()
            arr  = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            orig_gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if pix.n >= 3 else arr
        else:
            img       = cv2.imread(str(path))
            orig_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img is not None else None

        if orig_gray is not None:
            quality               = assess_document_quality(orig_gray)
            report.document_tier  = quality.tier.name
            report.recommended_preset = select_preset(quality).name
            report.skew_before      = quality.skew_angle
            report.occupancy_before = quality.occupancy_ratio
            report.blur_before      = quality.sharpness
    except Exception as exc:
        logger.warning("Quality assessment failed: %s", exc)

    before_text, before_conf = _run_doctr(path, ocr_model)
    report.before_chars      = len(before_text)
    report.before_words      = _count_words(before_text)
    report.before_confidence = before_conf
    report.before_text_sample = before_text[:200]

    processed_paths = preprocess_for_ocr(path, cfg)
    processed_path  = processed_paths[0] if processed_paths else path

    try:
        proc_img  = cv2.imread(str(processed_path))
        proc_gray = cv2.cvtColor(proc_img, cv2.COLOR_BGR2GRAY) if proc_img is not None else None
        if proc_gray is not None:
            report.skew_after      = _detect_skew(proc_gray)
            occ_a, _               = _detect_document_boundary(proc_gray)
            report.occupancy_after = occ_a
            report.blur_after      = detect_blur(proc_gray)
    except Exception as exc:
        logger.warning("Post-process geometry measurement failed: %s", exc)

    after_text, after_conf   = _run_doctr(processed_path, ocr_model)
    report.after_chars       = len(after_text)
    report.after_words       = _count_words(after_text)
    report.after_confidence  = after_conf
    report.after_text_sample = after_text[:200]

    report.char_improvement_pct = _pct_change(report.before_chars, report.after_chars)
    report.word_improvement_pct = _pct_change(report.before_words, report.after_words)
    report.confidence_delta     = round(report.after_confidence - report.before_confidence, 4)

    report.visual_path = _build_visual(path, processed_path, report, uid)

    if save_report:
        data = {**asdict(report), "quality_report": report.quality_report()}
        rp   = REPORT_DIR / f"{path.stem}_{uid}_{cfg.name}.json"
        rp.write_text(json.dumps(data, indent=2))
        report.report_path = str(rp)

    return report


def evaluate_all_presets(path, models: dict) -> list[OcrReport]:
    """Ablation: run every preset and rank by composite score."""
    from preprocessing import (
        DigitalPDFConfig, GrayscaleOnlyConfig, CleanScanConfig, TiltedScanConfig,
        DeskewOnlyConfig, ClaheOnlyConfig, CropOnlyConfig,
        LabReportConfig, PrescriptionConfig,
        DischargeSummaryConfig, HandwrittenConfig,
        LowQualityScanConfig, MobileCaptureConfig, AutoAdaptiveConfig,
    )
    presets = [
        AutoAdaptiveConfig(),
        DigitalPDFConfig(),
        GrayscaleOnlyConfig(),
        ClaheOnlyConfig(),
        DeskewOnlyConfig(),
        CropOnlyConfig(),
        CleanScanConfig(),
        TiltedScanConfig(),
        LabReportConfig(),
        PrescriptionConfig(),
        DischargeSummaryConfig(),
        HandwrittenConfig(),
        LowQualityScanConfig(),
        MobileCaptureConfig(),
    ]
    reports: list[OcrReport] = []
    for cfg in presets:
        try:
            r = evaluate_ocr_improvement(path, models, cfg=cfg)
            reports.append(r)
        except Exception as exc:
            logger.error("Preset %s failed: %s", cfg.name, exc)
    reports.sort(key=lambda r: r.composite_score(), reverse=True)
    print_comparison_table(reports)
    csv_path   = REPORT_DIR / f"{Path(path).stem}_preset_comparison.csv"
    chart_path = REPORT_DIR / f"{Path(path).stem}_preset_comparison.png"
    export_csv(reports, csv_path)
    try:
        plot_comparison_chart(reports, chart_path)
    except Exception as exc:
        logger.warning("chart failed: %s", exc)
    return reports


def recommend_best_preset(reports: list[OcrReport]) -> OcrReport:
    if not reports:
        raise ValueError("reports list is empty")
    best = max(reports, key=lambda r: r.composite_score())
    if best.composite_score() < 0:
        logger.warning(
            "Best preset '%s' has negative composite score (%.4f)",
            best.preset_name, best.composite_score(),
        )
    return best


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT / VISUALISATION (v4-compatible)
# ══════════════════════════════════════════════════════════════════════════════

def export_csv(reports: list[OcrReport], out_path: Path) -> None:
    out_path   = Path(out_path)
    fieldnames = [
        "preset_name", "document_tier",
        "before_chars", "after_chars", "char_improvement_pct",
        "before_words", "after_words", "word_improvement_pct",
        "before_confidence", "after_confidence", "confidence_delta",
        "skew_before", "skew_after",
        "occupancy_before", "occupancy_after",
        "blur_before", "blur_after",
        "composite_score",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in reports:
            writer.writerow({
                "preset_name":          r.preset_name,
                "document_tier":        r.document_tier,
                "before_chars":         r.before_chars,
                "after_chars":          r.after_chars,
                "char_improvement_pct": round(r.char_improvement_pct, 2),
                "before_words":         r.before_words,
                "after_words":          r.after_words,
                "word_improvement_pct": round(r.word_improvement_pct, 2),
                "before_confidence":    round(r.before_confidence, 4),
                "after_confidence":     round(r.after_confidence, 4),
                "confidence_delta":     round(r.confidence_delta, 4),
                "skew_before":          round(r.skew_before, 2),
                "skew_after":           round(r.skew_after, 2),
                "occupancy_before":     round(r.occupancy_before, 4),
                "occupancy_after":      round(r.occupancy_after, 4),
                "blur_before":          round(r.blur_before, 2),
                "blur_after":           round(r.blur_after, 2),
                "composite_score":      round(r.composite_score(), 4),
            })


def plot_comparison_chart(reports: list[OcrReport], out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not reports:
        return
    labels      = [r.preset_name for r in reports]
    conf_deltas = [r.confidence_delta for r in reports]
    char_pcts   = [r.char_improvement_pct / 100.0 for r in reports]
    word_pcts   = [r.word_improvement_pct / 100.0 for r in reports]
    x     = np.arange(len(labels))
    width = 0.25
    fig, ax = plt.subplots(figsize=(max(14, len(labels) * 1.5), 6))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")
    b1 = ax.bar(x - width, conf_deltas, width, label="Conf Δ",      color="#4cc9f0", alpha=0.88)
    b2 = ax.bar(x,         char_pcts,   width, label="Chars Δ (%)", color="#7209b7", alpha=0.88)
    b3 = ax.bar(x + width, word_pcts,   width, label="Words Δ (%)", color="#f72585", alpha=0.88)
    for bar in list(b1) + list(b2) + list(b3):
        bar.set_edgecolor("white")
        bar.set_linewidth(0.4)
    ax.axhline(0, color="white", linewidth=0.6, linestyle="--", alpha=0.4)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right", color="white", fontsize=8)
    ax.tick_params(axis="y", colors="white")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["bottom", "left"]:
        ax.spines[spine].set_color("#444")
    ax.set_title(
        f"OCR Preset Comparison — {reports[0].file_name}",
        color="white", fontsize=11, pad=14,
    )
    ax.set_ylabel("Improvement (raw / fraction)", color="white", fontsize=9)
    ax.legend(facecolor="#0f3460", edgecolor="#444", labelcolor="white", fontsize=8)
    best_i = max(range(len(reports)), key=lambda i: reports[i].composite_score())
    top_y  = max(conf_deltas[best_i], char_pcts[best_i], word_pcts[best_i], 0.0)
    ax.annotate(
        "◀ BEST",
        xy=(x[best_i], top_y),
        xytext=(x[best_i], top_y + 0.05),
        color="#ffd60a", fontsize=8, ha="center",
        arrowprops=dict(arrowstyle="->", color="#ffd60a", lw=1.0),
    )
    plt.tight_layout()
    plt.savefig(str(out_path), dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)


def print_report(report: OcrReport) -> None:
    q = report.quality_report()
    print(f"\n{'='*66}")
    print(f"  OCR Report — {report.file_name}  [{report.preset_name}]")
    if report.document_tier:
        print(f"  Tier: {report.document_tier}  →  recommended: {report.recommended_preset}")
    print(f"{'='*66}")
    print(f"  {'Metric':<36} {'Before':>8} {'After':>8} {'Δ':>10}")
    print(f"  {'-'*64}")
    print(f"  {'Characters':<36} {q['before_characters']:>8} {q['after_characters']:>8} "
          f"{q['char_improvement_pct']:>+9.1f}%")
    print(f"  {'Words':<36} {q['before_words']:>8} {q['after_words']:>8} "
          f"{q['word_improvement_pct']:>+9.1f}%")
    print(f"  {'docTR Confidence':<36} {q['before_confidence']:>8.4f} {q['after_confidence']:>8.4f} "
          f"{q['confidence_delta']:>+9.4f}")
    print(f"  {'Skew angle (°)':<36} {q['skew_before']:>+8.1f} {q['skew_after']:>+8.1f}")
    print(f"  {'Occupancy ratio':<36} {q['occupancy_before']:>8.3f} {q['occupancy_after']:>8.3f}")
    print(f"  {'Sharpness (Laplacian var)':<36} {q['blur_before']:>8.0f} {q['blur_after']:>8.0f}")
    print(f"  {'Composite score':<36} {'':>8} {'':>8} {report.composite_score():>+9.4f}")
    if report.visual_path:
        print(f"\n  Visual: {report.visual_path}")
    if report.report_path:
        print(f"  JSON:   {report.report_path}")
    print(f"{'='*66}\n")


def print_comparison_table(reports: list[OcrReport]) -> None:
    if not reports:
        print("No reports.")
        return
    print(f"\n{'='*90}")
    print(f"  Preset Comparison — {reports[0].file_name}")
    print(f"{'='*90}")
    print(f"  {'Preset':<22} {'Tier':>14} {'Chars Δ':>9} {'Words Δ':>9} "
          f"{'Conf Δ':>9} {'Skew Δ':>7} {'Score':>8}  {'Best?'}")
    print(f"  {'-'*86}")
    for i, r in enumerate(reports):
        marker = "◀ BEST" if i == 0 else ""
        tier   = r.document_tier[:14] if r.document_tier else "—"
        skew_d = r.skew_after - r.skew_before
        print(
            f"  {r.preset_name:<22} {tier:>14} "
            f"{r.char_improvement_pct:>+8.1f}% "
            f"{r.word_improvement_pct:>+8.1f}% "
            f"{r.confidence_delta:>+8.4f} "
            f"{skew_d:>+6.1f}° "
            f"{r.composite_score():>+7.4f}  {marker}"
        )
    print(f"{'='*90}\n")