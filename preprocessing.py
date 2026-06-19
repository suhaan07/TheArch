"""
TheArch — Confidence-Aware OCR Preprocessing Pipeline  (v5)
=============================================================
Core design change from v4
--------------------------
v4 made preprocessing decisions based on *image metrics alone* (sharpness,
skew, occupancy) — before any OCR ran. This caused catastrophic regressions on
already-good documents (Code_Generated_Image: 0.8979 → 0.5881).

v5 is confidence-aware:

  Stage 1  Run docTR on the original image to get a baseline confidence score.
  Stage 2  Decide which candidate branches to generate, based on that score:

           conf >= 0.90  → return original immediately (no preprocessing)
           conf 0.80-0.90 → evaluate: original, grayscale_only, clahe_only
           conf 0.60-0.80 → evaluate: original, deskew_only, clahe_only, moderate
           conf < 0.60   → evaluate: original + all arms (aggressive pipeline)

           Geometric overrides (applied regardless of confidence band):
             skew > 3°    → always include deskew_only arm
             occupancy < 0.5 → always include crop_only arm

  Stage 3  Run OCR on all candidate arms in parallel.
  Stage 4  Return the arm with the highest confidence.
           The original is always a candidate — preprocessing is never forced.

Public API (unchanged contract with ingestion.py)
-------------------------------------------------
    preprocess_for_ocr(path, cfg=None) → list[Path]

New exports used by ocr_evaluation_v5.py
-----------------------------------------
    confidence_aware_preprocess(path, ocr_fn)  → BestCandidate
    assess_document_quality(gray)   → DocumentQuality
    select_preset(quality)          → PreprocessConfig
    DocumentTier                    (enum)
    DocumentQuality, BestCandidate  (dataclasses)
    PreprocessConfig + all subclasses
    detect_blur(gray)               → float
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional, Union

import cv2
import numpy as np

logger = logging.getLogger("heydoc.preprocessing")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")
    )
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ── Output directory ──────────────────────────────────────────────────────────
PREPROCESSED_DIR = Path("preprocessed")
PREPROCESSED_DIR.mkdir(exist_ok=True)

# ── Confidence band thresholds ────────────────────────────────────────────────
CONF_HIGH        = 0.90   # return original immediately
CONF_MEDIUM_HIGH = 0.80   # light ops only
CONF_MEDIUM      = 0.60   # moderate ops
# below 0.60     → aggressive ops

# ── Geometric override thresholds ─────────────────────────────────────────────
SKEW_DESKEW_THRESHOLD      = 3.0   # degrees — always add deskew_only arm
OCCUPANCY_CROP_THRESHOLD   = 0.50  # always add crop_only arm

# ── Tunable image-metric thresholds ──────────────────────────────────────────
THRESHOLDS = {
    "blur_sharp_min":           80.0,
    "blur_sharp_high":         600.0,
    "blur_recover_max":        120.0,
    "noise_high":               0.15,
    "noise_low":                0.04,
    "denoise_noise_min":        0.055,
    "contrast_low":             0.15,
    "contrast_high":            0.35,
    "clahe_contrast_max":       0.30,
    "thresh_contrast_max":      0.28,
    "brightness_dark":          0.30,
    "brightness_bright":        0.85,
    "text_density_low":         0.01,
    "text_density_high":        0.25,
    "skew_trivial":             1.0,
    "skew_moderate":            3.0,
    "skew_severe":              8.0,
    "skew_max_safe":           22.0,
    "occupancy_good":           0.75,
    "occupancy_moderate":       0.50,
    "occupancy_low":            0.30,
    "occupancy_full_bleed_std": 18.0,
    "occupancy_border_frac":    0.02,
    "occupancy_quad_min_ratio": 0.50,
    "occupancy_quad_span_frac": 0.85,
    "digital_sharp_min":       500.0,
    "digital_contrast_min":     0.20,
    "digital_noise_max":        0.06,
    "digital_occupancy_min":    0.80,
    "hw_edge_density_high":     0.18,
    "hw_stroke_var_high":       38.0,
    "hw_cc_irregularity":       0.45,
    "hw_score_threshold":       0.78,
    "hw_cc_cv_threshold":       0.55,
    "hw_stroke_height_cv_threshold": 0.45,
    "perspective_min_area":     0.15,
}


# ══════════════════════════════════════════════════════════════════════════════
# ENUMS AND DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

class DocumentTier(Enum):
    HIGH_QUALITY   = auto()
    CLEAN_SCAN     = auto()
    TILTED_SCAN    = auto()
    LOW_QUALITY    = auto()
    MOBILE_CAPTURE = auto()
    HANDWRITTEN    = auto()


@dataclass
class DocumentQuality:
    sharpness:          float = 0.0
    blur_score:         float = 0.0
    noise_level:        float = 0.0
    contrast:           float = 0.0
    brightness:         float = 0.0
    text_density:       float = 0.0
    skew_angle:         float = 0.0
    occupancy_ratio:    float = 1.0
    has_document_box:   bool  = False
    handwriting_score:  float = 0.0
    cc_size_cv:         float = 0.0
    stroke_height_cv:   float = 0.0
    is_likely_digital:  bool  = False
    tier:               DocumentTier = DocumentTier.CLEAN_SCAN
    recommended_preset: str          = "AutoAdaptiveConfig"
    recommendation:     str          = ""

    def as_dict(self) -> dict:
        return {
            "tier":               self.tier.name,
            "sharpness":          round(self.sharpness, 2),
            "blur_score":         round(self.blur_score, 4),
            "noise_level":        round(self.noise_level, 4),
            "contrast":           round(self.contrast, 4),
            "brightness":         round(self.brightness, 4),
            "text_density":       round(self.text_density, 4),
            "skew_angle":         round(self.skew_angle, 2),
            "occupancy_ratio":    round(self.occupancy_ratio, 4),
            "has_document_box":   self.has_document_box,
            "handwriting_score":  round(self.handwriting_score, 4),
            "cc_size_cv":         round(self.cc_size_cv, 4),
            "stroke_height_cv":   round(self.stroke_height_cv, 4),
            "is_likely_digital":  self.is_likely_digital,
            "recommended_preset": self.recommended_preset,
            "recommendation":     self.recommendation,
        }


@dataclass
class CandidateResult:
    """OCR result for one preprocessing arm."""
    arm_name:   str
    image_path: Path
    image:      np.ndarray   # the preprocessed grayscale image
    confidence: float
    char_count: int
    text:       str


@dataclass
class BestCandidate:
    """
    Output of confidence_aware_preprocess().
    winner is the arm that achieved the highest OCR confidence.
    """
    winner:           CandidateResult
    baseline:         CandidateResult          # original — always run
    all_candidates:   list[CandidateResult]    # all arms evaluated
    baseline_conf:    float                    # original confidence (Stage 1)
    conf_band:        str                      # "high" / "medium_high" / "medium" / "low"
    skew_angle:       float
    occupancy_ratio:  float
    quality:          DocumentQuality


# ══════════════════════════════════════════════════════════════════════════════
# PRESET CONFIGS (unchanged from v4)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PreprocessConfig:
    name: str = "base"
    do_deskew:                  bool  = False
    do_perspective_correction:  bool  = False
    do_grayscale:               bool  = True
    do_clahe:                   bool  = False
    clahe_clip_limit:           float = 2.0
    clahe_tile_grid:            int   = 8
    do_denoise:                 bool  = False
    denoise_h:                  float = 7.0
    denoise_template_size:      int   = 7
    denoise_search_size:        int   = 21
    do_sharpen:                 bool  = False
    sharpen_amount:             float = 0.5
    do_blur_recovery:           bool  = False
    blur_recovery_strength:     float = 0.6
    do_threshold:               bool  = False
    threshold_block_size:       int   = 21
    threshold_c:                int   = 10
    do_enhance_handwriting:     bool  = False
    hw_dilate_kernel:           int   = 2
    do_remove_border:           bool  = False
    border_fraction:            float = 0.01
    do_upscale:                 bool  = False
    upscale_target_height:      int   = 2200


@dataclass
class DigitalPDFConfig(PreprocessConfig):
    name:         str  = "digital_pdf"
    do_grayscale: bool = True


@dataclass
class GrayscaleOnlyConfig(PreprocessConfig):
    """Just converts to grayscale — the lightest possible op."""
    name:         str  = "grayscale_only"
    do_grayscale: bool = True


@dataclass
class DeskewOnlyConfig(PreprocessConfig):
    """Deskew only — used as geometric-override arm."""
    name:         str  = "deskew_only"
    do_grayscale: bool = True
    do_deskew:    bool = True


@dataclass
class ClaheOnlyConfig(PreprocessConfig):
    """CLAHE only — light contrast enhancement."""
    name:             str   = "clahe_only"
    do_grayscale:     bool  = True
    do_clahe:         bool  = True
    clahe_clip_limit: float = 1.5
    clahe_tile_grid:  int   = 8


@dataclass
class CropOnlyConfig(PreprocessConfig):
    """Perspective / crop only — used as geometric-override arm for low-occupancy."""
    name:                       str  = "crop_only"
    do_grayscale:               bool = True
    do_perspective_correction:  bool = True


@dataclass
class CleanScanConfig(PreprocessConfig):
    name:             str   = "clean_scan"
    do_grayscale:     bool  = True
    do_deskew:        bool  = True
    do_clahe:         bool  = True
    clahe_clip_limit: float = 1.5
    clahe_tile_grid:  int   = 8


@dataclass
class TiltedScanConfig(PreprocessConfig):
    name:                       str   = "tilted_scan"
    do_grayscale:               bool  = True
    do_deskew:                  bool  = True
    do_perspective_correction:  bool  = True
    do_clahe:                   bool  = True
    clahe_clip_limit:           float = 1.5
    clahe_tile_grid:            int   = 8
    do_remove_border:           bool  = True
    border_fraction:            float = 0.005


@dataclass
class LabReportConfig(PreprocessConfig):
    name:             str   = "lab_report"
    do_grayscale:     bool  = True
    do_clahe:         bool  = True
    clahe_clip_limit: float = 1.5
    clahe_tile_grid:  int   = 8
    do_deskew:        bool  = True


@dataclass
class PrescriptionConfig(PreprocessConfig):
    name:                   str   = "prescription"
    do_grayscale:           bool  = True
    do_clahe:               bool  = True
    clahe_clip_limit:       float = 2.5
    clahe_tile_grid:        int   = 8
    do_deskew:              bool  = True
    do_enhance_handwriting: bool  = True
    hw_dilate_kernel:       int   = 2
    do_denoise:             bool  = True
    denoise_h:              float = 5.0


@dataclass
class DischargeSummaryConfig(PreprocessConfig):
    name:             str   = "discharge_summary"
    do_grayscale:     bool  = True
    do_clahe:         bool  = True
    clahe_clip_limit: float = 1.8
    clahe_tile_grid:  int   = 8
    do_deskew:        bool  = True


@dataclass
class HandwrittenConfig(PreprocessConfig):
    name:                   str   = "handwritten"
    do_grayscale:           bool  = True
    do_clahe:               bool  = True
    clahe_clip_limit:       float = 3.0
    clahe_tile_grid:        int   = 8
    do_deskew:              bool  = True
    do_enhance_handwriting: bool  = True
    hw_dilate_kernel:       int   = 2
    do_denoise:             bool  = True
    denoise_h:              float = 5.0
    do_remove_border:       bool  = True


@dataclass
class LowQualityScanConfig(PreprocessConfig):
    name:                str   = "low_quality_scan"
    do_grayscale:        bool  = True
    do_clahe:            bool  = True
    clahe_clip_limit:    float = 2.5
    clahe_tile_grid:     int   = 8
    do_denoise:          bool  = True
    denoise_h:           float = 9.0
    do_deskew:           bool  = True
    do_threshold:        bool  = True
    threshold_block_size: int  = 21
    threshold_c:          int  = 8
    do_remove_border:    bool  = True
    do_sharpen:          bool  = True
    sharpen_amount:      float = 0.4


@dataclass
class MobileCaptureConfig(PreprocessConfig):
    name:                       str   = "mobile_capture"
    do_grayscale:               bool  = True
    do_perspective_correction:  bool  = True
    do_deskew:                  bool  = True
    do_clahe:                   bool  = True
    clahe_clip_limit:           float = 3.0
    clahe_tile_grid:            int   = 8
    do_denoise:                 bool  = True
    denoise_h:                  float = 7.0
    do_blur_recovery:           bool  = True
    blur_recovery_strength:     float = 0.5
    do_threshold:               bool  = True
    threshold_block_size:       int   = 25
    threshold_c:                int   = 10
    do_remove_border:           bool  = True


@dataclass
class AutoAdaptiveConfig(PreprocessConfig):
    """Runtime-adaptive: Stage 1 OCR → confidence-band selection → multi-arm eval."""
    name: str = "auto_adaptive"


# ══════════════════════════════════════════════════════════════════════════════
# MEASUREMENT FUNCTIONS (unchanged from v4)
# ══════════════════════════════════════════════════════════════════════════════

def detect_blur(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _estimate_noise(gray: np.ndarray) -> float:
    blurred  = cv2.GaussianBlur(gray, (5, 5), 0)
    residual = gray.astype(np.float32) - blurred.astype(np.float32)
    return float(np.std(residual) / 255.0)


def _estimate_contrast(gray: np.ndarray) -> float:
    return (float(np.percentile(gray, 95)) - float(np.percentile(gray, 5))) / 255.0


def _estimate_text_density(gray: np.ndarray) -> float:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(np.sum(binary == 0)) / float(binary.size)


def _detect_skew(gray: np.ndarray) -> float:
    T = THRESHOLDS
    max_safe = T["skew_max_safe"]
    try:
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180,
            threshold=80, minLineLength=80, maxLineGap=10,
        )
        if lines is not None and len(lines) >= 5:
            angles = []
            for ln in lines:
                x1, y1, x2, y2 = ln[0]
                if x2 != x1:
                    a = math.degrees(math.atan2(y2 - y1, x2 - x1))
                    if abs(a) < 45:
                        angles.append(a)
            if len(angles) >= 5:
                return float(np.clip(np.median(angles), -max_safe, max_safe))
    except Exception:
        pass
    try:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 3))
        dilated = cv2.dilate(binary, kernel, iterations=1)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest) > 500:
                rect  = cv2.minAreaRect(largest)
                angle = rect[2]
                if angle < -45:
                    angle += 90
                return float(np.clip(angle, -max_safe, max_safe))
    except Exception:
        pass
    return 0.0


def _detect_document_boundary(gray: np.ndarray) -> tuple[float, bool]:
    T  = THRESHOLDS
    h, w = gray.shape[:2]
    frame_area = h * w

    bw = max(2, int(w * T["occupancy_border_frac"]))
    bh = max(2, int(h * T["occupancy_border_frac"]))
    border_px = np.concatenate([
        gray[:bh, :].ravel(), gray[-bh:, :].ravel(),
        gray[:, :bw].ravel(), gray[:, -bw:].ravel(),
    ])
    if float(np.std(border_px)) > T["occupancy_full_bleed_std"]:
        return 1.0, False

    content_ratio = 0.5
    try:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ys, xs = np.where(binary > 0)
        if len(xs) >= 50:
            x0, x1 = np.percentile(xs, [0.5, 99.5])
            y0, y1 = np.percentile(ys, [0.5, 99.5])
            bbox_area = max(1.0, (x1 - x0)) * max(1.0, (y1 - y0))
            content_ratio = float(min(bbox_area / frame_area, 1.0))
    except Exception:
        pass

    try:
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges   = cv2.Canny(blurred, 30, 120)
        kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        dilated = cv2.dilate(edges, kernel, iterations=3)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
                area  = cv2.contourArea(cnt)
                ratio = area / frame_area
                if ratio < T["occupancy_quad_min_ratio"]:
                    continue
                peri   = cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, 0.03 * peri, True)
                if len(approx) not in (4, 5):
                    continue
                _, _, qbw, qbh = cv2.boundingRect(approx)
                spans_edge = (
                    qbw >= T["occupancy_quad_span_frac"] * w
                    or qbh >= T["occupancy_quad_span_frac"] * h
                )
                if not spans_edge:
                    continue
                if ratio < content_ratio:
                    continue
                return float(min(ratio, 1.0)), True
    except Exception:
        pass
    return content_ratio, False


def _hw_zero_result() -> dict:
    return {"score": 0.0, "cc_size_cv": 0.0, "stroke_height_cv": 0.0}


def _estimate_handwriting_score(gray: np.ndarray) -> dict:
    T = THRESHOLDS
    try:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ys, xs = np.where(binary > 0)
        if len(xs) < 50:
            return _hw_zero_result()

        x0, x1 = np.percentile(xs, [0.5, 99.5]).astype(int)
        y0, y1 = np.percentile(ys, [0.5, 99.5]).astype(int)
        x0, y0 = max(0, x0), max(0, y0)
        x1 = min(gray.shape[1], x1 + 1)
        y1 = min(gray.shape[0], y1 + 1)

        roi_gray = gray[y0:y1, x0:x1]
        if roi_gray.size < 100:
            return _hw_zero_result()

        # Signal 1 — Canny edge density in content bbox
        edges_roi = cv2.Canny(roi_gray, 50, 150)
        edge_dens  = float(np.sum(edges_roi > 0)) / roi_gray.size
        high = T["hw_edge_density_high"]
        score_edge = float(np.clip(edge_dens / high, 0, 1))

        # Signal 2 — local Laplacian variance (stroke irregularity)
        lap_var    = float(cv2.Laplacian(roi_gray, cv2.CV_64F).var())
        score_var  = float(np.clip(lap_var / T["hw_stroke_var_high"], 0, 1))

        # Signal 3 — connected-component size CV
        roi_bin = cv2.threshold(roi_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        n, _, stats, _ = cv2.connectedComponentsWithStats(roi_bin, connectivity=8)
        cc_size_cv       = 0.0
        stroke_height_cv = 0.0
        if n > 2:
            areas   = stats[1:, cv2.CC_STAT_AREA].astype(float)
            heights = stats[1:, cv2.CC_STAT_HEIGHT].astype(float)
            areas   = areas[areas > 4]
            heights = heights[heights > 2]
            if len(areas) > 2:
                cc_size_cv = float(np.std(areas) / (np.mean(areas) + 1e-9))
            if len(heights) > 2:
                stroke_height_cv = float(np.std(heights) / (np.mean(heights) + 1e-9))

        score_cc = float(np.clip(cc_size_cv / T["hw_cc_irregularity"], 0, 1))
        composite = (score_edge * 0.35 + score_var * 0.30 + score_cc * 0.35)
        return {
            "score": round(composite, 4),
            "cc_size_cv": round(cc_size_cv, 4),
            "stroke_height_cv": round(stroke_height_cv, 4),
        }
    except Exception:
        return _hw_zero_result()


# ══════════════════════════════════════════════════════════════════════════════
# QUALITY ASSESSMENT & TIER SELECTION (unchanged from v4)
# ══════════════════════════════════════════════════════════════════════════════

def assess_document_quality(gray: np.ndarray) -> DocumentQuality:
    T = THRESHOLDS
    q = DocumentQuality()

    q.sharpness        = detect_blur(gray)
    q.blur_score       = max(0.0, 1.0 - q.sharpness / T["blur_sharp_high"])
    q.noise_level      = _estimate_noise(gray)
    q.contrast         = _estimate_contrast(gray)
    q.brightness       = float(np.mean(gray)) / 255.0
    q.text_density     = _estimate_text_density(gray)
    q.skew_angle       = _detect_skew(gray)

    hw = _estimate_handwriting_score(gray)
    q.handwriting_score = hw["score"]
    q.cc_size_cv        = hw["cc_size_cv"]
    q.stroke_height_cv  = hw["stroke_height_cv"]
    q.occupancy_ratio, q.has_document_box = _detect_document_boundary(gray)

    q.is_likely_digital = (
        q.sharpness       >= T["digital_sharp_min"]
        and q.contrast    >= T["digital_contrast_min"]
        and q.noise_level <= T["digital_noise_max"]
        and abs(q.skew_angle) < T["skew_moderate"]
        and q.occupancy_ratio >= T["digital_occupancy_min"]
    )

    is_sharp     = q.sharpness >= T["blur_sharp_min"]
    is_low_noise = q.noise_level <= T["noise_high"]
    has_geometry_issue = (
        abs(q.skew_angle) >= T["skew_moderate"]
        or (q.occupancy_ratio < T["occupancy_moderate"] and abs(q.skew_angle) >= T["skew_trivial"])
        or q.occupancy_ratio < T["occupancy_low"]
    )

    if q.is_likely_digital:
        q.tier               = DocumentTier.HIGH_QUALITY
        q.recommended_preset = "DigitalPDFConfig"
        q.recommendation     = "Digital PDF. Grayscale-only."
    elif has_geometry_issue and is_sharp and is_low_noise:
        q.tier               = DocumentTier.TILTED_SCAN
        q.recommended_preset = "TiltedScanConfig"
        q.recommendation     = "Geometry issue. Deskew + crop."
    elif (not has_geometry_issue) and (
        q.contrast < T["contrast_low"] or not is_sharp or not is_low_noise
    ):
        q.tier               = DocumentTier.LOW_QUALITY
        q.recommended_preset = "LowQualityScanConfig"
        q.recommendation     = "Low quality. Full conservative pipeline."
    elif has_geometry_issue and (not is_sharp or not is_low_noise):
        q.tier               = DocumentTier.MOBILE_CAPTURE
        q.recommended_preset = "MobileCaptureConfig"
        q.recommendation     = "Mobile capture. Perspective + tone pipeline."
    elif (
        q.handwriting_score    >= T["hw_score_threshold"]
        and q.cc_size_cv       >= T["hw_cc_cv_threshold"]
        and q.stroke_height_cv >= T["hw_stroke_height_cv_threshold"]
    ):
        q.tier               = DocumentTier.HANDWRITTEN
        q.recommended_preset = "HandwrittenConfig"
        q.recommendation     = "Handwritten. Stroke-enhancement pipeline."
    else:
        q.tier               = DocumentTier.CLEAN_SCAN
        q.recommended_preset = "CleanScanConfig"
        q.recommendation     = "Good scan. Light CLAHE + deskew."

    logger.info(
        "  Quality: tier=%-14s  sharp=%6.1f  noise=%.3f  contrast=%.3f  "
        "skew=%+5.1f°  occ=%.2f  hw=%.2f  digital=%s",
        q.tier.name, q.sharpness, q.noise_level, q.contrast,
        q.skew_angle, q.occupancy_ratio, q.handwriting_score, q.is_likely_digital,
    )
    return q


def select_preset(quality: DocumentQuality) -> PreprocessConfig:
    mapping = {
        DocumentTier.HIGH_QUALITY:   DigitalPDFConfig,
        DocumentTier.CLEAN_SCAN:     CleanScanConfig,
        DocumentTier.TILTED_SCAN:    TiltedScanConfig,
        DocumentTier.LOW_QUALITY:    LowQualityScanConfig,
        DocumentTier.MOBILE_CAPTURE: MobileCaptureConfig,
        DocumentTier.HANDWRITTEN:    HandwrittenConfig,
    }
    return mapping.get(quality.tier, CleanScanConfig)()


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL OPERATIONS (unchanged from v4)
# ══════════════════════════════════════════════════════════════════════════════

def auto_deskew(img: np.ndarray, detected_angle: Optional[float] = None) -> np.ndarray:
    gray  = img if len(img.shape) == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    angle = detected_angle if detected_angle is not None else _detect_skew(gray)
    if abs(angle) < THRESHOLDS["skew_trivial"]:
        return img
    h, w   = img.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    M      = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    cos_a  = abs(M[0, 0])
    sin_a  = abs(M[0, 1])
    new_w  = int(h * sin_a + w * cos_a)
    new_h  = int(h * cos_a + w * sin_a)
    M[0, 2] += (new_w / 2.0) - cx
    M[1, 2] += (new_h / 2.0) - cy
    border = 255 if len(img.shape) == 2 else (255, 255, 255)
    result = cv2.warpAffine(img, M, (new_w, new_h),
                            flags=cv2.INTER_CUBIC,
                            borderMode=cv2.BORDER_CONSTANT,
                            borderValue=border)
    logger.info("  deskew: angle=%+.2f°  %dx%d → %dx%d", angle, w, h, new_w, new_h)
    return result


def auto_perspective_correction(img: np.ndarray) -> np.ndarray:
    try:
        gray   = img if len(img.shape) == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w   = gray.shape[:2]
        T      = THRESHOLDS
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges   = cv2.Canny(blurred, 30, 120)
        kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        dilated = cv2.dilate(edges, kernel, iterations=3)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return img
        doc_contour = None
        for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
            area  = cv2.contourArea(cnt)
            ratio = area / (h * w)
            if ratio < T["occupancy_quad_min_ratio"]:
                continue
            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.025 * peri, True)
            if len(approx) == 4:
                _, _, qbw, qbh = cv2.boundingRect(approx)
                if (qbw >= T["occupancy_quad_span_frac"] * w
                        or qbh >= T["occupancy_quad_span_frac"] * h):
                    doc_contour = approx
                    break
        if doc_contour is None:
            return img
        pts     = doc_contour.reshape(4, 2).astype(np.float32)
        s       = pts.sum(axis=1)
        d       = np.diff(pts, axis=1).ravel()
        ordered = np.array([
            pts[np.argmin(s)], pts[np.argmin(d)],
            pts[np.argmax(s)], pts[np.argmax(d)],
        ], dtype=np.float32)
        tl, tr, br, bl = ordered
        out_w  = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
        out_h  = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
        dst    = np.array([[0, 0], [out_w - 1, 0],
                           [out_w - 1, out_h - 1], [0, out_h - 1]], dtype=np.float32)
        M      = cv2.getPerspectiveTransform(ordered, dst)
        border = 255 if len(img.shape) == 2 else (255, 255, 255)
        warped = cv2.warpPerspective(img, M, (out_w, out_h), borderValue=border)
        logger.info("  perspective: %dx%d → %dx%d", w, h, out_w, out_h)
        return warped
    except Exception as exc:
        logger.warning("  perspective failed: %s — using original", exc)
        return img


def enhance_handwriting(img: np.ndarray, dilate_kernel: int = 2) -> np.ndarray:
    if len(img.shape) != 2:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe    = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(img)
    if dilate_kernel > 0:
        k       = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_kernel, dilate_kernel))
        inv     = cv2.bitwise_not(enhanced)
        dilated = cv2.dilate(inv, k, iterations=1)
        enhanced = cv2.bitwise_not(dilated)
    return enhanced


def _apply_blur_recovery(img: np.ndarray, strength: float = 0.5) -> np.ndarray:
    if len(img.shape) != 2:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred   = cv2.GaussianBlur(img, (0, 0), sigmaX=2.0)
    sharpened = cv2.addWeighted(img, 1.0 + strength, blurred, -strength, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def _remove_border(img: np.ndarray, fraction: float = 0.01) -> np.ndarray:
    h, w = img.shape[:2]
    dy   = max(1, int(h * fraction))
    dx   = max(1, int(w * fraction))
    return img[dy: h - dy, dx: w - dx]


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE ORCHESTRATOR (unchanged from v4)
# ══════════════════════════════════════════════════════════════════════════════

def _apply_preset(
    img:     np.ndarray,
    cfg:     PreprocessConfig,
    quality: Optional[DocumentQuality] = None,
) -> np.ndarray:
    T    = THRESHOLDS
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()

    if isinstance(cfg, DigitalPDFConfig):
        return gray

    if cfg.do_upscale and gray.shape[0] < cfg.upscale_target_height:
        scale = cfg.upscale_target_height / gray.shape[0]
        gray  = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    if cfg.do_perspective_correction:
        skip_perspective = (
            quality is not None
            and abs(quality.skew_angle) < T["skew_moderate"]
            and not quality.has_document_box
        )
        if not skip_perspective:
            gray = auto_perspective_correction(gray)

    if cfg.do_deskew:
        angle = quality.skew_angle if quality is not None else _detect_skew(gray)
        if abs(angle) >= T["skew_trivial"]:
            gray = auto_deskew(gray, detected_angle=angle)

    if cfg.do_denoise:
        noise = quality.noise_level if quality is not None else _estimate_noise(gray)
        if noise >= T["denoise_noise_min"]:
            gray = cv2.fastNlMeansDenoising(
                gray,
                h=cfg.denoise_h,
                templateWindowSize=cfg.denoise_template_size,
                searchWindowSize=cfg.denoise_search_size,
            )

    if cfg.do_enhance_handwriting:
        gray = enhance_handwriting(gray, dilate_kernel=cfg.hw_dilate_kernel)

    if cfg.do_clahe:
        contrast = quality.contrast if quality is not None else _estimate_contrast(gray)
        if contrast < T["clahe_contrast_max"]:
            clahe = cv2.createCLAHE(
                clipLimit=cfg.clahe_clip_limit,
                tileGridSize=(cfg.clahe_tile_grid, cfg.clahe_tile_grid),
            )
            gray = clahe.apply(gray)

    if cfg.do_blur_recovery:
        sharpness = quality.sharpness if quality is not None else detect_blur(gray)
        if sharpness < T["blur_recover_max"]:
            gray = _apply_blur_recovery(gray, strength=cfg.blur_recovery_strength)

    if cfg.do_sharpen and not cfg.do_blur_recovery:
        k         = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
        sharpened = cv2.filter2D(gray, -1, k)
        gray      = cv2.addWeighted(gray, 1.0 - cfg.sharpen_amount,
                                    sharpened, cfg.sharpen_amount, 0)

    if cfg.do_threshold and not cfg.do_enhance_handwriting:
        contrast = quality.contrast if quality is not None else _estimate_contrast(gray)
        if contrast < T["thresh_contrast_max"]:
            gray = cv2.adaptiveThreshold(
                gray, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                cfg.threshold_block_size,
                cfg.threshold_c,
            )

    if cfg.do_remove_border:
        gray = _remove_border(gray, fraction=cfg.border_fraction)

    return gray


# ══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE-AWARE MULTI-ARM SELECTOR  ← THE NEW CORE
# ══════════════════════════════════════════════════════════════════════════════

def _select_arms(
    baseline_conf: float,
    quality: DocumentQuality,
) -> list[tuple[str, PreprocessConfig]]:
    """
    Given Stage-1 OCR confidence and quality metrics, return the list of
    (arm_name, config) pairs to evaluate.

    The original image is ALWAYS arm 0 (the safe baseline).
    Arms are chosen to be as minimal as possible — we only add heavier
    operations when confidence is low enough to justify the risk.
    """
    arms: list[tuple[str, PreprocessConfig]] = []

    skew = abs(quality.skew_angle)
    occ  = quality.occupancy_ratio

    # ── Band: HIGH (≥ 0.90) ────────────────────────────────────────────────────
    # Return immediately in the caller — no arms needed.

    # ── Band: MEDIUM-HIGH (0.80–0.90) ─────────────────────────────────────────
    if baseline_conf >= CONF_MEDIUM_HIGH:
        arms.append(("grayscale_only", GrayscaleOnlyConfig()))
        arms.append(("clahe_only",     ClaheOnlyConfig()))

    # ── Band: MEDIUM (0.60–0.80) ──────────────────────────────────────────────
    elif baseline_conf >= CONF_MEDIUM:
        arms.append(("clahe_only",  ClaheOnlyConfig()))
        arms.append(("deskew_only", DeskewOnlyConfig()))
        arms.append(("moderate",    CleanScanConfig()))

    # ── Band: LOW (< 0.60) ────────────────────────────────────────────────────
    else:
        arms.append(("clahe_only",          ClaheOnlyConfig()))
        arms.append(("deskew_only",         DeskewOnlyConfig()))
        arms.append(("moderate",            CleanScanConfig()))
        arms.append(("low_quality_pipeline", LowQualityScanConfig()))
        arms.append(("mobile_capture",      MobileCaptureConfig()))

    # ── Geometric overrides (always added, regardless of confidence band) ──────
    if skew >= SKEW_DESKEW_THRESHOLD:
        names = {a[0] for a in arms}
        if "deskew_only" not in names:
            logger.info("  geometric override: adding deskew_only arm (skew=%.1f°)", skew)
            arms.append(("deskew_only", DeskewOnlyConfig()))

    if occ < OCCUPANCY_CROP_THRESHOLD:
        names = {a[0] for a in arms}
        if "crop_only" not in names:
            logger.info("  geometric override: adding crop_only arm (occupancy=%.2f)", occ)
            arms.append(("crop_only", CropOnlyConfig()))

    return arms


def confidence_aware_preprocess(
    bgr:          np.ndarray,
    ocr_fn:       Callable[[np.ndarray], tuple[str, float]],
    stem:         str = "doc",
    quality:      Optional[DocumentQuality] = None,
) -> BestCandidate:
    """
    Confidence-aware multi-arm preprocessing selector.

    Args:
        bgr:    BGR image (already loaded from disk / rasterised from PDF).
        ocr_fn: Callable that accepts a grayscale uint8 ndarray and returns
                (text: str, confidence: float). This is your docTR wrapper.
        stem:   Used for naming saved PNG candidates.
        quality: Pre-computed DocumentQuality. If None, assessed internally.

    Returns:
        BestCandidate — winner is the arm with highest OCR confidence.
        The original is always a candidate, so quality can never decrease.

    Algorithm
    ---------
    Stage 1  Run OCR on the original grayscale image → baseline confidence.
    Stage 2  If conf ≥ 0.90, return original immediately.
             Otherwise select arms based on confidence band + geometric signals.
    Stage 3  Run OCR on all arm candidates (original already done → reuse).
    Stage 4  Pick the arm with highest confidence. Ties → prefer original.
    """
    # ── Convert to grayscale for assessment and Stage-1 OCR ───────────────────
    gray_orig = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if len(bgr.shape) == 3 else bgr.copy()

    # ── Assess quality (needed for skew/occupancy geometric overrides) ─────────
    if quality is None:
        quality = assess_document_quality(gray_orig)

    # ── Stage 1: OCR on original ───────────────────────────────────────────────
    logger.info("  [Stage 1] OCR on original image …")
    orig_text, orig_conf = ocr_fn(gray_orig)
    orig_char_count = len(orig_text)

    # Save original as a candidate image
    orig_path = PREPROCESSED_DIR / f"{stem}_original.png"
    cv2.imwrite(str(orig_path), gray_orig)

    baseline = CandidateResult(
        arm_name   = "original",
        image_path = orig_path,
        image      = gray_orig,
        confidence = orig_conf,
        char_count = orig_char_count,
        text       = orig_text,
    )

    # Determine confidence band label for reporting
    if orig_conf >= CONF_HIGH:
        conf_band = "high"
    elif orig_conf >= CONF_MEDIUM_HIGH:
        conf_band = "medium_high"
    elif orig_conf >= CONF_MEDIUM:
        conf_band = "medium"
    else:
        conf_band = "low"

    logger.info(
        "  [Stage 1] baseline conf=%.4f  band=%s  skew=%+.1f°  occ=%.2f",
        orig_conf, conf_band, quality.skew_angle, quality.occupancy_ratio,
    )

    # ── Stage 2: Early exit for high-confidence documents ─────────────────────
    if orig_conf >= CONF_HIGH:
        logger.info(
            "  [Stage 2] conf=%.4f ≥ %.2f → returning original immediately (no preprocessing)",
            orig_conf, CONF_HIGH,
        )
        return BestCandidate(
            winner          = baseline,
            baseline        = baseline,
            all_candidates  = [baseline],
            baseline_conf   = orig_conf,
            conf_band       = conf_band,
            skew_angle      = quality.skew_angle,
            occupancy_ratio = quality.occupancy_ratio,
            quality         = quality,
        )

    # ── Stage 2: Select arms ───────────────────────────────────────────────────
    arms = _select_arms(orig_conf, quality)
    logger.info(
        "  [Stage 2] %d preprocessing arm(s) to evaluate: %s",
        len(arms), [a[0] for a in arms],
    )

    # ── Stage 3: Run OCR on all arms ──────────────────────────────────────────
    all_candidates: list[CandidateResult] = [baseline]

    for arm_name, cfg in arms:
        try:
            logger.info("  [Stage 3] arm=%s …", arm_name)
            processed = _apply_preset(bgr, cfg, quality=quality)

            arm_path = PREPROCESSED_DIR / f"{stem}_{arm_name}.png"
            cv2.imwrite(str(arm_path), processed)

            arm_text, arm_conf = ocr_fn(processed)
            logger.info(
                "    arm=%-24s  conf=%.4f  (%+.4f vs baseline)  chars=%d",
                arm_name, arm_conf, arm_conf - orig_conf, len(arm_text),
            )
            all_candidates.append(CandidateResult(
                arm_name   = arm_name,
                image_path = arm_path,
                image      = processed,
                confidence = arm_conf,
                char_count = len(arm_text),
                text       = arm_text,
            ))
        except Exception as exc:
            logger.warning("  arm=%s failed: %s", arm_name, exc)

    # ── Stage 4: Pick winner (highest confidence; ties → baseline) ────────────
    winner = max(all_candidates, key=lambda c: c.confidence)

    delta = winner.confidence - orig_conf
    if delta <= 0:
        # No arm beat the original — use original
        winner = baseline
        logger.info(
            "  [Stage 4] No arm improved on original (best delta=%.4f) — keeping original",
            delta,
        )
    else:
        logger.info(
            "  [Stage 4] Winner: arm=%s  conf=%.4f  (+%.4f vs original)",
            winner.arm_name, winner.confidence, delta,
        )

    return BestCandidate(
        winner          = winner,
        baseline        = baseline,
        all_candidates  = all_candidates,
        baseline_conf   = orig_conf,
        conf_band       = conf_band,
        skew_angle      = quality.skew_angle,
        occupancy_ratio = quality.occupancy_ratio,
        quality         = quality,
    )


# ══════════════════════════════════════════════════════════════════════════════
# RASTERISER (unchanged from v4)
# ══════════════════════════════════════════════════════════════════════════════

def _rasterise_pdf(path: Path, dpi: int = 200) -> list[np.ndarray]:
    try:
        import fitz
        doc   = fitz.open(str(path))
        mat   = fitz.Matrix(dpi / 72, dpi / 72)
        pages = []
        for page in doc:
            pix = page.get_pixmap(matrix=mat)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            if pix.n == 4:
                bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            elif pix.n == 1:
                bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            else:
                bgr = arr.copy()
            pages.append(bgr)
        doc.close()
        return pages
    except Exception as exc:
        logger.error("  PDF rasterise failed: %s", exc)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT — ingestion.py contract (backward-compatible)
# ══════════════════════════════════════════════════════════════════════════════

def preprocess_for_ocr(
    path: Union[str, Path],
    cfg:  Optional[PreprocessConfig] = None,
    ocr_fn: Optional[Callable[[np.ndarray], tuple[str, float]]] = None,
) -> list[Path]:
    """
    Preprocess a document for OCR.

    If ocr_fn is provided (recommended), uses the confidence-aware pipeline:
      - Runs Stage-1 OCR to get baseline confidence.
      - Selects and evaluates only the arms that can plausibly help.
      - Returns the image that achieved the highest OCR confidence.

    If ocr_fn is None, falls back to the v4 behaviour (image-metrics only).

    Contract with ingestion.py (unchanged):
        preprocessed_paths = preprocess_for_ocr(path, ocr_fn=my_doctr_fn)
        ocr_input = preprocessed_paths[0]
    """
    path   = Path(path)
    suffix = path.suffix.lower()
    logger.info("preprocess_for_ocr: %s", path.name)

    # Load
    if suffix == ".pdf":
        pages_bgr = _rasterise_pdf(path)
        if not pages_bgr:
            logger.error("preprocess: failed to rasterise %s", path.name)
            return []
    else:
        bgr = cv2.imread(str(path))
        if bgr is None:
            logger.error("preprocess: cannot read %s", path.name)
            return []
        pages_bgr = [bgr]

    out_paths: list[Path] = []

    for idx, bgr in enumerate(pages_bgr):
        stem   = f"{path.stem}" + (f"_p{idx+1}" if len(pages_bgr) > 1 else "")

        if ocr_fn is not None:
            # ── Confidence-aware path ─────────────────────────────────────────
            result = confidence_aware_preprocess(bgr, ocr_fn, stem=stem)
            out_paths.append(result.winner.image_path)
            logger.info(
                "  page %d → winner arm=%s  conf=%.4f  (baseline=%.4f  band=%s)",
                idx + 1, result.winner.arm_name, result.winner.confidence,
                result.baseline_conf, result.conf_band,
            )

        else:
            # ── v4 fallback (image-metrics only, no OCR feedback) ─────────────
            logger.warning(
                "  preprocess_for_ocr called without ocr_fn — "
                "falling back to image-metrics-only selection (v4 behaviour). "
                "Pass ocr_fn= for confidence-aware preprocessing."
            )
            gray_assess = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            quality     = assess_document_quality(gray_assess)
            resolved    = (select_preset(quality) if (cfg is None or isinstance(cfg, AutoAdaptiveConfig))
                           else cfg)
            processed   = _apply_preset(bgr, resolved, quality=quality)
            out_name    = f"{stem}_{resolved.name}.png"
            out_path    = PREPROCESSED_DIR / out_name
            cv2.imwrite(str(out_path), processed)
            out_paths.append(out_path)
            logger.info("  saved → %s", out_path.name)

    return out_paths