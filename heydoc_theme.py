"""HeyDoc — visual constants, CSS, and HTML helpers."""

import streamlit as st

# ── Semantic type config (single source of truth for both roles) ──────────────
SEMANTIC = {
    "medication_history": {
        "icon": "💊", "color": "#2563EB", "bg": "#EFF6FF",
        "border": "#BFDBFE", "label": "Medications",
    },
    "diagnosis": {
        "icon": "🔴", "color": "#DC2626", "bg": "#FEF2F2",
        "border": "#FECACA", "label": "Diagnosis",
    },
    "lab_reports": {
        "icon": "🧪", "color": "#D97706", "bg": "#FFFBEB",
        "border": "#FDE68A", "label": "Lab Reports",
    },
    "surgical_history": {
        "icon": "⚕️", "color": "#EA580C", "bg": "#FFF7ED",
        "border": "#FED7AA", "label": "Surgical History",
    },
    "follow_up_notes": {
        "icon": "📋", "color": "#059669", "bg": "#ECFDF5",
        "border": "#A7F3D0", "label": "Follow-up",
    },
    "patient_information": {
        "icon": "👤", "color": "#4B5563", "bg": "#F9FAFB",
        "border": "#D1D5DB", "label": "Patient Info",
    },
    "imaging_scan": {
        "icon": "🩻", "color": "#7C3AED", "bg": "#F5F3FF",
        "border": "#DDD6FE", "label": "Imaging",
    },
}

OCR_LABELS = {
    "plaintext":      ("📄", "Plain text"),
    "pymupdf":        ("📑", "Digital PDF"),
    "doctr":          ("🔍", "docTR OCR"),
    "gemini":         ("✨", "Gemini Vision"),
    "doctr_fallback": ("🔄", "docTR fallback"),
    "gemini_vision":  ("📸", "Gemini Vision"),
}

PATIENT_PRIMARY = "#2563EB"
PATIENT_DARK    = "#1D4ED8"
STAFF_PRIMARY   = "#1E3A5F"
STAFF_ACCENT    = "#2563EB"

# ── Base CSS (shared) ──────────────────────────────────────────────────────────
_BASE = """
<style>
#MainMenu, footer, header {visibility: hidden;}
.block-container {padding-top: 1.2rem !important; padding-bottom: 2rem !important;}

.hd-card {
    background: white;
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1rem;
    border: 1px solid #E5E7EB;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.hd-page-title {
    font-size: 1.5rem;
    font-weight: 700;
    margin-bottom: 0.2rem;
    color: #111827;
}
.hd-page-sub {
    font-size: 0.88rem;
    color: #6B7280;
    margin-bottom: 1.4rem;
}
.sem-pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 600;
    margin: 2px;
    white-space: nowrap;
}
.ai-disclaimer {
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    border-radius: 8px;
    padding: 0.55rem 1rem;
    font-size: 0.81rem;
    color: #92400E;
    margin-bottom: 0.9rem;
}
.answer-box {
    background: #F8FAFC;
    border-left: 4px solid #2563EB;
    border-radius: 0 8px 8px 0;
    padding: 1rem 1.25rem;
    margin: 0.75rem 0;
    line-height: 1.65;
}
.source-chip {
    display: inline-block;
    background: #EFF6FF;
    border: 1px solid #BFDBFE;
    border-radius: 6px;
    padding: 2px 9px;
    font-size: 0.76rem;
    color: #1D4ED8;
    margin: 2px;
}
.confidence-bar-wrap {
    background: #E5E7EB;
    border-radius: 999px;
    height: 6px;
    width: 100%;
    margin: 4px 0 2px;
}
.confidence-bar-fill {
    height: 6px;
    border-radius: 999px;
    background: linear-gradient(90deg, #2563EB, #10B981);
}
.queue-pos {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px; height: 40px;
    border-radius: 50%;
    background: #2563EB;
    color: white;
    font-weight: 700;
    font-size: 1.1rem;
}
.queue-row {
    background: white;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
}
.status-waiting  { color: #D97706; font-weight: 600; }
.status-active   { color: #059669; font-weight: 600; }
.status-done     { color: #6B7280; font-weight: 600; }
.intake-section  { margin-bottom: 1.4rem; }
.intake-label    { font-size: 0.78rem; font-weight: 600; color: #6B7280; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.3rem; }
.confirm-banner  { background: #ECFDF5; border: 1px solid #6EE7B7; border-radius: 8px; padding: 0.75rem 1rem; color: #065F46; font-weight: 600; margin-top: 1rem; }
.role-card {
    border-radius: 16px;
    padding: 2.5rem 2rem;
    text-align: center;
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
    border: 2px solid transparent;
}
.role-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
}
.role-card-patient { background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%); border-color: #BFDBFE; }
.role-card-staff   { background: linear-gradient(135deg, #1E3A5F 0%, #1e4d8c 100%); color: white; border-color: #2563EB; }
</style>
"""

_PATIENT_SIDEBAR = f"""
<style>
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {PATIENT_PRIMARY} 0%, {PATIENT_DARK} 100%) !important;
}}
[data-testid="stSidebar"] * {{ color: white !important; }}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ color: rgba(255,255,255,0.72) !important; font-size:0.82rem; }}
[data-testid="stSidebar"] .stRadio > label {{ color: rgba(255,255,255,0.55) !important; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.18) !important; }}
</style>
"""

_STAFF_SIDEBAR = f"""
<style>
[data-testid="stSidebar"] {{
    background: {STAFF_PRIMARY} !important;
}}
[data-testid="stSidebar"] * {{ color: white !important; }}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ color: rgba(255,255,255,0.65) !important; font-size:0.82rem; }}
[data-testid="stSidebar"] .stRadio > label {{ color: rgba(255,255,255,0.45) !important; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.15) !important; }}
</style>
"""


def inject_patient_css():
    st.markdown(_BASE + _PATIENT_SIDEBAR, unsafe_allow_html=True)


def inject_staff_css():
    st.markdown(_BASE + _STAFF_SIDEBAR, unsafe_allow_html=True)


# ── HTML helpers ───────────────────────────────────────────────────────────────

def sem_pill(sem_type: str) -> str:
    cfg = SEMANTIC.get(sem_type, SEMANTIC["patient_information"])
    return (
        f'<span class="sem-pill" style="background:{cfg["bg"]};color:{cfg["color"]};'
        f'border:1px solid {cfg["border"]}">'
        f'{cfg["icon"]} {cfg["label"]}</span>'
    )


def ai_disclaimer() -> str:
    return (
        '<div class="ai-disclaimer">'
        '⚠️ <strong>AI-assisted only — not a clinical diagnosis.</strong> '
        'HeyDoc surfaces information from your records; it does not replace a doctor. '
        'Always consult a qualified physician before making any health decision.'
        '</div>'
    )


def page_header(title: str, subtitle: str = ""):
    st.markdown(f'<div class="hd-page-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="hd-page-sub">{subtitle}</div>', unsafe_allow_html=True)


def confidence_bar(score: float) -> str:
    pct = int(score * 100)
    color = "#10B981" if score > 0.75 else "#D97706" if score > 0.5 else "#DC2626"
    return (
        f'<div style="font-size:0.78rem;color:#6B7280;margin-top:4px">'
        f'Confidence: <strong style="color:{color}">{pct}%</strong></div>'
        f'<div class="confidence-bar-wrap"><div class="confidence-bar-fill" style="width:{pct}%;background:{color}"></div></div>'
    )


def ocr_badge(method: str) -> str:
    icon, label = OCR_LABELS.get(method, ("📄", method))
    return f'<span class="source-chip">{icon} {label}</span>'
