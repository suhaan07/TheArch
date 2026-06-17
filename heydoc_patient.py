"""HeyDoc — all patient-facing views."""

import streamlit as st
from pathlib import Path

import ingestion
import imaging
from heydoc_theme import (
    inject_patient_css, page_header, sem_pill, ai_disclaimer,
    confidence_bar, ocr_badge, SEMANTIC,
)
from heydoc_vault import show_vault
from heydoc_mock import (
    mock_rag_query as rag_query,   # ← SWAP: replace with retrieval.rag_query when ready
    add_to_queue, get_patient_queue_entry, remove_from_queue,
    DEPARTMENTS, DOCTORS,
)
# from retrieval import rag_query  # ← real backend; uncomment and remove mock line above


# ── Sidebar nav ────────────────────────────────────────────────────────────────

def _sidebar():
    with st.sidebar:
        st.markdown(
            '<div style="font-size:1.6rem;font-weight:800;letter-spacing:-0.5px">🏥 HeyDoc</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="font-size:0.82rem;opacity:0.75;margin-bottom:0.25rem">'
            f'Patient: <strong>{st.session_state.user_name}</strong></div>'
            f'<div style="font-size:0.75rem;opacity:0.55;margin-bottom:1rem">'
            f'ID: {st.session_state.patient_id}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.markdown('<div style="font-size:0.7rem;opacity:0.5;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:0.4rem">Menu</div>', unsafe_allow_html=True)

        views = {
            "upload":  "📤  Upload Records",
            "vault":   "🗄️  My Vault",
            "ask":     "💬  Ask HeyDoc",
            "queue":   "🏥  Check-in & Queue",
        }
        for key, label in views.items():
            active = st.session_state.get("view") == key
            style  = "font-weight:700;opacity:1" if active else "opacity:0.8"
            if st.button(label, key=f"nav_{key}", use_container_width=True):
                st.session_state.view = key
                st.rerun()

        st.markdown("---")
        if st.button("Sign out", use_container_width=True):
            for k in ["role", "user_id", "user_name", "patient_id", "view", "chat_history"]:
                st.session_state.pop(k, None)
            st.rerun()


# ── View 1: Upload ─────────────────────────────────────────────────────────────

def _show_upload(models: dict, imaging_models: dict):
    page_header("Upload Records", "Add your medical documents — PDFs, scanned reports, prescriptions, X-rays.")

    tab_docs, tab_scans = st.tabs(["📄 Documents (PDF / text / images)", "🩻 Scan Images (X-ray / CT / MRI)"])

    with tab_docs:
        uploaded = st.file_uploader(
            "Drop files here or click to browse",
            accept_multiple_files=True,
            type=["pdf", "jpg", "jpeg", "png", "txt"],
            label_visibility="collapsed",
        )
        if uploaded:
            st.markdown(f"**{len(uploaded)} file(s) selected**")
            for f in uploaded:
                st.caption(f"  📎 {f.name}  ({f.size // 1024} KB)")

            if st.button("Ingest documents →", type="primary"):
                bar = st.progress(0)
                for idx, f in enumerate(uploaded):
                    tmp = Path(f"/content/{f.name}")
                    try:
                        tmp.parent.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        tmp = Path(f.name)
                    tmp.write_bytes(f.read())

                    with st.spinner(f"Processing {f.name}…"):
                        r = ingestion.ingest_document(st.session_state.patient_id, tmp, models)

                    bar.progress((idx + 1) / len(uploaded))

                    if r["status"] == "ok":
                        col_l, col_r = st.columns([3, 2])
                        with col_l:
                            st.markdown(
                                f'✅ **{Path(r["file"]).name}**  '
                                + sem_pill(r.get("semantic_type", "patient_information")),
                                unsafe_allow_html=True,
                            )
                            st.markdown(
                                f'{ocr_badge(r["method"])} &nbsp; '
                                f'<span style="font-size:0.82rem;color:#6B7280">'
                                f'`{r["doc_type"]}` · {r["chunks"]} chunks</span>',
                                unsafe_allow_html=True,
                            )
                        with col_r:
                            if r.get("doctor"):
                                st.caption(f"👨‍⚕️ {r['doctor']}")
                            if r.get("visit_date"):
                                st.caption(f"📅 {r['visit_date']}")
                            if r.get("drugs"):
                                st.caption(f"💊 {', '.join(r['drugs'][:3])}")
                        st.markdown("---")
                    else:
                        st.error(f"❌ {Path(r['file']).name}: {r.get('reason','error')}")

    with tab_scans:
        biovil_note = (
            "BioViL-T secondary check active for chest X-rays ✅"
            if imaging_models.get("biovilt_available")
            else "BioViL-T not installed — using Gemini Vision only"
        )
        st.caption(f"📸 Gemini Vision will describe your scan. {biovil_note}")

        scan_files = st.file_uploader(
            "Upload scan images",
            accept_multiple_files=True,
            type=["jpg", "jpeg", "png", "bmp"],
            key="scan_up",
            label_visibility="collapsed",
        )
        if scan_files:
            for f in scan_files:
                mod = imaging.detect_modality(Path(f.name))
                st.caption(f"  🩻 {f.name} — detected: `{mod}`")

            if st.button("Describe & ingest scans →", type="primary", key="ingest_scans"):
                bar = st.progress(0)
                for idx, f in enumerate(scan_files):
                    tmp = Path(f"/content/scan_{f.name}")
                    try:
                        tmp.parent.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        tmp = Path(f"scan_{f.name}")
                    tmp.write_bytes(f.read())

                    with st.spinner(f"Describing {f.name} with Gemini Vision…"):
                        r = imaging.ingest_scan(
                            st.session_state.patient_id, tmp, models, imaging_models
                        )
                    bar.progress((idx + 1) / len(scan_files))

                    if r["status"] == "ok":
                        label = f"✅ **{Path(r['file']).name}** · `{r['modality']}`"
                        if r["is_abnormal"]:
                            label += "  ⚠️ **Abnormal flags detected**"
                        st.markdown(label)
                        if r["abnormal_flags"]:
                            st.warning("BioViL-T flagged: " + ", ".join(r["abnormal_flags"]))
                        with st.expander("Gemini description"):
                            st.caption(r["gemini_description"])
                    else:
                        st.error(f"❌ {Path(r['file']).name}: {r.get('reason','error')}")

        st.markdown("---")
        st.markdown("**OCR method guide**")
        guide_cols = st.columns(5)
        for i, (method, (icon, label)) in enumerate(
            [("plaintext",("📄","Plain text")), ("pymupdf",("📑","Digital PDF")),
             ("doctr",("🔍","docTR OCR")), ("gemini",("✨","Gemini Vision")),
             ("doctr_fallback",("🔄","docTR fallback"))]
        ):
            guide_cols[i].markdown(f"**{icon}** {label}", unsafe_allow_html=False)
            guide_cols[i].caption(method)


# ── View 2: Vault ──────────────────────────────────────────────────────────────

def _show_vault(models: dict):
    page_header("My Vault", "All your health records, organised by category.")
    show_vault(models["collection"], st.session_state.patient_id, clinical_mode=False)


# ── View 3: Ask HeyDoc ─────────────────────────────────────────────────────────

def _render_sources(sources: list):
    """Render source chips; handles both mock and real retrieval formats."""
    if not sources:
        return
    st.markdown("**Sources used:**")
    for s in sources:
        # Real retrieval.rag_query wraps metadata under "meta"; mock puts fields at top level
        meta      = s.get("meta", s)
        sem_type  = meta.get("semantic_type", s.get("semantic_type", "unknown"))
        file_name = meta.get("file_name",     s.get("file", "unknown"))
        date_str  = meta.get("visit_date",    s.get("date", ""))
        icon      = SEMANTIC.get(sem_type, {}).get("icon", "📄")

        rrf_score    = s.get("rrf_score")
        rerank_score = s.get("rerank_score")
        bm25_score   = s.get("bm25_score")
        vec_score    = s.get("score")

        has_scores = any(v is not None for v in [rrf_score, rerank_score, bm25_score, vec_score])
        header = f"{icon} **{file_name}** · `{sem_type}`"
        if date_str:
            header += f" · {date_str}"

        with st.expander(header, expanded=False):
            if s.get("text"):
                st.markdown(
                    f"<div style='background:#f8f9fa;padding:10px;border-radius:6px;"
                    f"font-size:0.85em;line-height:1.5'>{s['text'][:400]}"
                    f"{'…' if len(s['text']) > 400 else ''}</div>",
                    unsafe_allow_html=True,
                )
            if has_scores:
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("RRF",    rrf_score    if rrf_score    is not None else "—")
                sc2.metric("Rerank", rerank_score if rerank_score is not None else "—")
                sc3.metric("Vector", vec_score    if vec_score    is not None else "—")
                sc4.metric("BM25",   bm25_score   if bm25_score   is not None else "—")
            doc_type = meta.get("doc_type") or s.get("doc_type")
            doctor   = meta.get("doctor_name") or s.get("doctor")
            if doc_type or doctor:
                st.caption(
                    "  ".join(filter(None, [
                        f"`{doc_type}`" if doc_type else None,
                        f"Dr. {doctor}" if doctor   else None,
                    ]))
                )


def _show_ask(models: dict):
    page_header("Ask HeyDoc", "Ask anything about your health history.")
    st.markdown(ai_disclaimer(), unsafe_allow_html=True)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Render existing messages
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                st.markdown(
                    f'<div class="answer-box">{msg["content"]}</div>',
                    unsafe_allow_html=True,
                )
                _render_sources(msg.get("sources", []))
                if msg.get("confidence") is not None:
                    st.markdown(confidence_bar(msg["confidence"]), unsafe_allow_html=True)
                # Query trace (populated by real retrieval backend)
                if msg.get("norm_query") or msg.get("prompt"):
                    with st.expander("🔍 Query trace", expanded=False):
                        if msg.get("norm_query") and msg["norm_query"] != msg.get("question"):
                            st.markdown("**Normalised query** *(typo correction + abbreviation expansion)*")
                            st.code(msg["norm_query"], language=None)
                        if msg.get("prompt"):
                            st.markdown("**Full prompt sent to Gemini**")
                            st.code(msg["prompt"], language=None)
            else:
                st.markdown(msg["content"])

    # Chat input
    question = st.chat_input("Ask about your records, medications, diagnoses…")
    if question:
        st.session_state.chat_history.append({"role": "user", "content": question})

        with st.spinner("Searching your records…"):
            result = rag_query(
                patient_id=st.session_state.patient_id,
                question=question,
                models=models,
            )

        st.session_state.chat_history.append({
            "role":       "assistant",
            "content":    result["answer"],
            "sources":    result.get("sources", []),
            "confidence": result.get("confidence"),
            "norm_query": result.get("norm_query"),
            "prompt":     result.get("prompt"),
            "question":   question,
        })
        st.rerun()

    if st.session_state.chat_history:
        if st.button("Clear conversation", key="clear_chat"):
            st.session_state.chat_history = []
            st.rerun()


# ── View 4: Check-in & Queue ───────────────────────────────────────────────────

def _show_queue():
    page_header("Check-in & Queue", "Check in for your appointment and track your position.")

    pid   = st.session_state.patient_id
    name  = st.session_state.user_name
    entry = get_patient_queue_entry(pid)

    if entry:
        # Already checked in — show status
        st.success(f"✅ You're checked in! Token: **{entry['token']}**")

        status_color = {"active": "#059669", "waiting": "#D97706", "done": "#6B7280"}
        color = status_color.get(entry["status"], "#6B7280")

        st.markdown(
            f'<div class="hd-card" style="border-left:4px solid {color}">'
            f'<div style="display:flex;align-items:center;gap:1rem">'
            f'<div class="queue-pos">{entry["position"]}</div>'
            f'<div>'
            f'<div style="font-size:1.05rem;font-weight:700">Position #{entry["position"]}</div>'
            f'<div style="color:{color};font-weight:600;font-size:0.88rem">'
            f'{"🟢 You\'re next!" if entry["status"]=="active" else "🟡 Waiting…"}</div>'
            f'</div></div>'
            f'<div style="margin-top:1rem;display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem">'
            f'<div><div style="font-size:0.72rem;color:#6B7280;text-transform:uppercase">Department</div>'
            f'<div style="font-weight:600">{entry["department"]}</div></div>'
            f'<div><div style="font-size:0.72rem;color:#6B7280;text-transform:uppercase">Doctor</div>'
            f'<div style="font-weight:600">{entry["doctor"]}</div></div>'
            f'<div><div style="font-size:0.72rem;color:#6B7280;text-transform:uppercase">Est. wait</div>'
            f'<div style="font-weight:600">{entry["wait_minutes"]} min</div></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        col_refresh, col_cancel = st.columns([2, 1])
        if col_refresh.button("🔄 Refresh", use_container_width=True):
            st.rerun()
        if col_cancel.button("Cancel check-in", use_container_width=True):
            remove_from_queue(pid)
            st.rerun()

    else:
        # Check-in form
        st.markdown("**Select your appointment details to check in:**")
        with st.form("checkin_form"):
            dept    = st.selectbox("Department", DEPARTMENTS)
            doctors = DOCTORS.get(dept, ["Dr. —"])
            doctor  = st.selectbox("Doctor", doctors)
            confirm = st.form_submit_button("Check in →", type="primary")

        if confirm:
            new_entry = add_to_queue(pid, name, dept, doctor)
            st.success(
                f"✅ Checked in! Your token is **{new_entry['token']}** — "
                f"position **#{new_entry['position']}**, estimated wait **{new_entry['wait_minutes']} min**."
            )
            st.rerun()


# ── Patient app entry point ────────────────────────────────────────────────────

def show_patient_app(models: dict, imaging_models: dict):
    inject_patient_css()
    _sidebar()

    view = st.session_state.get("view", "upload")

    if view == "upload":
        _show_upload(models, imaging_models)
    elif view == "vault":
        _show_vault(models)
    elif view == "ask":
        _show_ask(models)
    elif view == "queue":
        _show_queue()
    else:
        _show_upload(models, imaging_models)
