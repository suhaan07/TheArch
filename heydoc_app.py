"""
HeyDoc — Main Streamlit entry point
=====================================
Run with:
    streamlit run heydoc_app.py

Two roles, completely separate interfaces:
  Patient  → upload records, browse vault, ask AI, check in to queue
  Staff    → patient lookup, clinical summary, intake form, queue dashboard
"""

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ingestion
import retrieval
import imaging
from heydoc_theme import PATIENT_PRIMARY, STAFF_PRIMARY
from heydoc_patient import show_patient_app
from heydoc_staff import show_staff_app

st.set_page_config(
    page_title="HeyDoc",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Model loading (cached — shared across both roles) ──────────────────────────

@st.cache_resource(show_spinner="Loading AI models…  (first run ~60s)")
def load_models(gemini_key: str):
    models = ingestion.init(gemini_api_key=gemini_key)
    retrieval.init_reranker(models)
    return models


@st.cache_resource(show_spinner="Loading imaging models (BioViL-T)…")
def load_imaging_models_cached():
    return imaging.load_imaging_models()


# ── Session state initialisation ───────────────────────────────────────────────

def _init():
    defaults = {
        "role":             None,   # "patient" | "staff"
        "user_name":        None,
        "patient_id":       None,   # set for patients; used as scope key throughout
        "view":             None,   # current page within role
        "chat_history":     [],
        "selected_patient": None,   # staff: currently viewed patient
        "gemini_key":       "",
        "models_loaded":    False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Landing page ───────────────────────────────────────────────────────────────

def _show_landing():
    # Inject minimal landing CSS (no sidebar theming here)
    st.markdown("""
    <style>
    #MainMenu, footer, header {visibility: hidden;}
    .block-container {padding-top: 3rem !important;}
    [data-testid="stSidebar"] {display: none;}
    </style>
    """, unsafe_allow_html=True)

    # Logo + tagline
    st.markdown(
        '<div style="text-align:center;padding:1rem 0 0.5rem">'
        '<div style="font-size:2.8rem;font-weight:800;letter-spacing:-1px;color:#111827">🏥 HeyDoc</div>'
        '<div style="font-size:1.05rem;color:#6B7280;margin-top:0.3rem">'
        'Your AI-powered health companion — intelligent, private, always with you.'
        '</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # Gemini API key (required to load models)
    key_col, _ = st.columns([1, 1])
    with key_col:
        gemini_key = st.text_input(
            "Gemini API Key",
            type="password",
            placeholder="AIza…",
            value=st.session_state.gemini_key,
            help="Required to run the AI pipeline. Get yours at aistudio.google.com",
        )
        if gemini_key:
            st.session_state.gemini_key = gemini_key

    st.markdown("<br>", unsafe_allow_html=True)

    # Role cards
    st.markdown(
        '<div style="text-align:center;font-size:0.88rem;color:#9CA3AF;margin-bottom:0.75rem">'
        'Choose how you\'re signing in</div>',
        unsafe_allow_html=True,
    )

    lcol, rcol = st.columns(2, gap="large")

    with lcol:
        st.markdown(
            f'<div class="role-card role-card-patient">'
            f'<div style="font-size:3rem">👤</div>'
            f'<div style="font-size:1.3rem;font-weight:700;color:#1D4ED8;margin:0.5rem 0">Patient</div>'
            f'<div style="font-size:0.88rem;color:#4B5563;line-height:1.5">'
            f'Upload your records, browse your health history, ask AI questions, and check in for appointments.'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        with st.form("patient_form"):
            p_name = st.text_input("Your name",       placeholder="e.g. Rahul Kumar")
            p_id   = st.text_input("Patient ID",      placeholder="e.g. patient_001",
                                   help="The ID assigned to you by your hospital. Used to scope all your records.")
            p_go   = st.form_submit_button("Sign in as Patient →", use_container_width=True, type="primary")
        if p_go:
            if not st.session_state.gemini_key:
                st.error("Please enter your Gemini API key above first.")
            elif not p_name.strip() or not p_id.strip():
                st.error("Please enter both your name and patient ID.")
            else:
                st.session_state.role       = "patient"
                st.session_state.user_name  = p_name.strip()
                st.session_state.patient_id = p_id.strip()
                st.session_state.view       = "upload"
                st.rerun()

    with rcol:
        st.markdown(
            f'<div class="role-card role-card-staff">'
            f'<div style="font-size:3rem">🩺</div>'
            f'<div style="font-size:1.3rem;font-weight:700;color:white;margin:0.5rem 0">Staff / Doctor</div>'
            f'<div style="font-size:0.88rem;color:rgba(255,255,255,0.78);line-height:1.5">'
            f'Look up patients, review clinical summaries, generate intake forms, and manage the OPD queue.'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        with st.form("staff_form"):
            s_name = st.text_input("Your name",  placeholder="e.g. Dr. Priya Mehta")
            s_id   = st.text_input("Staff ID",   placeholder="e.g. STAFF001",
                                   help="Your hospital staff ID. Used to identify you in the system.")
            s_go   = st.form_submit_button("Sign in as Staff →", use_container_width=True)
        if s_go:
            if not st.session_state.gemini_key:
                st.error("Please enter your Gemini API key above first.")
            elif not s_name.strip() or not s_id.strip():
                st.error("Please enter both your name and staff ID.")
            else:
                st.session_state.role      = "staff"
                st.session_state.user_name = s_name.strip()
                st.session_state.view      = "lookup"
                st.rerun()

    # Footer
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(
        '<div style="text-align:center;font-size:0.75rem;color:#D1D5DB">'
        'HeyDoc · The Arch · IIT Kharagpur Hackathon · '
        'AI-assisted only — not a clinical diagnostic tool.'
        '</div>',
        unsafe_allow_html=True,
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    _init()

    if st.session_state.role is None:
        # Show landing — no models needed yet
        _show_landing()
        return

    # Models are loaded once and cached; key is the gemini API key
    models         = load_models(st.session_state.gemini_key)
    imaging_models = load_imaging_models_cached()

    if st.session_state.role == "patient":
        show_patient_app(models, imaging_models)
    elif st.session_state.role == "staff":
        show_staff_app(models)


main()
