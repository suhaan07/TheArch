"""
HeyDoc — Document authenticity validators
==========================================
Deterministic, no-LLM checks for whether an Indian ID number is well-formed
enough to be real, and whether insurance/prescription documents carry the
structural markers a genuine one would have.

None of this proves a document is genuinely government/insurer/hospital
issued -- that needs an authoritative lookup (UIDAI/NMC/IRDAI APIs), which
is out of scope here. This only raises the bar against careless/lazy fakes
(made-up numbers, bare keywords, missing required fields).
"""
from __future__ import annotations

import re

# ── Aadhaar — Verhoeff checksum ─────────────────────────────────────────────
# Standard, publicly documented tables (not Aadhaar-specific; the algorithm
# detects all single-digit substitution and adjacent-transposition errors).

_D_TABLE = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]

_P_TABLE = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_valid(digits: str) -> bool:
    """True if `digits` (including its own last digit as the check digit)
    passes the Verhoeff checksum."""
    if not digits.isdigit():
        return False
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _D_TABLE[c][_P_TABLE[i % 8][int(ch)]]
    return c == 0


def aadhaar_valid(digits: str) -> bool:
    """UIDAI never issues a citizen Aadhaar starting with 0 or 1; the 12th
    digit is a Verhoeff check digit over all 12."""
    digits = re.sub(r"\s", "", digits)
    return len(digits) == 12 and digits[0] not in "01" and verhoeff_valid(digits)


# ── PAN — 4th character holder-type sanity check ────────────────────────────
# The 10th-character check digit's algorithm is not publicly disclosed by
# the Income Tax Department, so it can't be verified independently — only
# the holder-type character can be sanity-checked.

PAN_HOLDER_TYPES = set("CPHFATBLJG")


def pan_holder_type_valid(pan: str) -> bool:
    pan = pan.strip().upper()
    return len(pan) == 10 and pan[3] in PAN_HOLDER_TYPES


# ── Insurance — structural markers a genuine policy document carries ───────

INSURER_NAMES = [
    "star health", "hdfc ergo", "icici lombard", "niva bupa", "max bupa",
    "care health", "religare", "bajaj allianz", "new india assurance",
    "national insurance", "tata aig", "united india", "oriental insurance",
    "sbi health", "aditya birla health",
]

INSURANCE_STRUCTURE_MARKERS = ["sum insured", "sum assured", "tpa", "irdai", "irda"]


def insurance_structure_score(text: str) -> int:
    """How many recognizable insurer names / standard policy-document terms
    appear in the text -- a genuine policy document/cashless card almost
    always has at least one; a bare fake usually has none."""
    tl = text.lower()
    return sum(1 for term in INSURER_NAMES + INSURANCE_STRUCTURE_MARKERS if term in tl)


# ── Prescriptions — doctor registration number (NMC-mandated) ──────────────

DOCTOR_REG_NO_PAT = re.compile(r"reg(?:istration|d)?\.?\s*no\.?\s*[:\-]?\s*[A-Za-z0-9/\-]{3,}", re.I)
