"""
TheArch — Streamlit UI
======================
Run with:
    streamlit run app.py

Both ingestion.py and app.py must be in the same directory.
"""

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ingestion
import retrieval
import imaging

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TheArch",
    page_icon="🏥",
    layout="wide",
)

SEMANTIC_ICONS = {
    "medication_history":  "🟦",
    "diagnosis":           "🟥",
    "lab_reports":         "🟨",
    "surgical_history":    "🟧",
    "follow_up_notes":     "🟩",
    "patient_information": "⬜",
}


# ── Model loading (cached per session) ────────────────────────────────────────
@st.cache_resource(show_spinner="Loading AI models — this takes ~60s on first run...")
def load_models(gemini_key: str):
    models = ingestion.init(gemini_api_key=gemini_key)
    retrieval.init_reranker(models)   # adds models["reranker"] in-place
    return models


@st.cache_resource(show_spinner="Loading imaging models (BioViL-T for chest X-ray)...")
def load_imaging_models():
    return imaging.load_imaging_models()


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🏥 TheArch")
    st.caption("AI-powered patient health record management")
    st.divider()

    gemini_key = st.text_input(
        "Gemini API Key",
        type="password",
        placeholder="AIza...",
        help="Get your key from aistudio.google.com",
    )
    patient_id = st.text_input(
        "Patient ID",
        value="patient_001",
        help="Unique identifier for this patient. Different IDs = separate vaults.",
    )
    st.divider()
    st.caption(f"Drive: /content/drive/MyDrive/TheArch/")
    st.caption(f"ChromaDB: {ingestion.CHROMA_DIR}")

if not gemini_key:
    st.info("👈 Enter your Gemini API key in the sidebar to get started.")
    st.stop()

models         = load_models(gemini_key)
imaging_models = load_imaging_models()
collection     = models["collection"]

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_upload, tab_vault, tab_query = st.tabs(["📤 Upload", "🗂 Patient Vault", "💬 Ask AI"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.subheader(f"Upload documents for patient: `{patient_id}`")

    col_a, col_b = st.columns(2, gap="large")

    # ── Option A: file picker ─────────────────────────────────────────────────
    with col_a:
        st.markdown("#### Option A — Upload directly")
        st.caption("Files are saved temporarily in /content/ for this session. "
                   "Chunks are permanently stored in ChromaDB on Drive.")

        uploaded_files = st.file_uploader(
            "Choose files",
            accept_multiple_files=True,
            type=["pdf", "jpg", "jpeg", "png", "txt"],
            label_visibility="collapsed",
        )

        if uploaded_files:
            st.write(f"{len(uploaded_files)} file(s) selected:")
            for f in uploaded_files:
                st.caption(f"  {f.name}  ({f.size // 1024} KB)")

            if st.button("Ingest selected files", type="primary", key="ingest_upload"):
                progress_bar = st.progress(0)
                results      = []
                for idx, f in enumerate(uploaded_files):
                    tmp = Path(f"/content/{f.name}")
                    tmp.write_bytes(f.read())
                    with st.spinner(f"Processing {f.name}..."):
                        r = ingestion.ingest_document(patient_id, tmp, models)
                    results.append(r)
                    progress_bar.progress((idx + 1) / len(uploaded_files))

                st.success(f"✅ Ingested {len(results)} file(s)")
                for r in results:
                    if r["status"] == "ok":
                        icon = "✅"
                        st.markdown(
                            f"{icon} **{Path(r['file']).name}** — "
                            f"`{r['doc_type']}` | `{r['method']}` | "
                            f"**{r['chunks']} chunks** | "
                            f"Dr. {r['doctor'] or '—'} | {r['visit_date'] or '—'}"
                        )
                        if r["drugs"]:
                            st.caption(f"   Drugs detected: {', '.join(r['drugs'][:4])}")
                    else:
                        st.error(f"❌ {Path(r['file']).name}: {r.get('reason', 'error')}")

    # ── Option B: from Drive ──────────────────────────────────────────────────
    with col_b:
        st.markdown("#### Option B — From Drive folder")
        st.caption(f"Drop files into `MyDrive/TheArch/uploads/` then click below.")

        SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".txt"}

        if st.button("🔄 Refresh file list", key="refresh_drive"):
            st.rerun()

        drive_files = sorted(
            [f for f in ingestion.UPLOAD_DIR.iterdir() if f.suffix.lower() in SUPPORTED_EXTS]
        ) if ingestion.UPLOAD_DIR.exists() else []

        if not drive_files:
            st.info("No supported files found in Drive uploads folder yet.")
        else:
            st.write(f"**{len(drive_files)} file(s) in Drive:**")
            for f in drive_files:
                st.caption(f"  📄 {f.name}  ({f.stat().st_size // 1024} KB)")

            if st.button("Ingest from Drive", type="primary", key="ingest_drive"):
                progress_bar = st.progress(0)
                results      = []
                for idx, f in enumerate(drive_files):
                    with st.spinner(f"Processing {f.name}..."):
                        r = ingestion.ingest_document(patient_id, f, models)
                    results.append(r)
                    progress_bar.progress((idx + 1) / len(drive_files))

                st.success(f"✅ Ingested {len(results)} file(s)")
                for r in results:
                    if r["status"] == "ok":
                        st.markdown(
                            f"✅ **{Path(r['file']).name}** — "
                            f"`{r['doc_type']}` | `{r['method']}` | "
                            f"**{r['chunks']} chunks**"
                        )
                    else:
                        st.error(f"❌ {Path(r['file']).name}: {r.get('reason', 'error')}")

    # ── OCR method legend ─────────────────────────────────────────────────────
    st.divider()
    st.markdown("**OCR method legend:**")
    cols = st.columns(5)
    legends = [
        ("plaintext",      "Direct read, no OCR"),
        ("pymupdf",        "Digital PDF, text layer"),
        ("doctr",          "Scanned/typed, high confidence"),
        ("gemini",         "Handwritten, Gemini Vision"),
        ("doctr_fallback", "Gemini failed, kept docTR"),
    ]
    for i, (method, desc) in enumerate(legends):
        cols[i].markdown(f"**`{method}`**")
        cols[i].caption(desc)

    # ── Medical Scan ingestion ─────────────────────────────────────────────────
    st.divider()
    st.markdown("#### 🩻 Medical Scan Ingestion (X-ray / CT / MRI / Ultrasound)")
    st.caption(
        "For raw scan *images* (pixel data), not text reports. "
        "Gemini Vision generates a clinical description; "
        "BioViL-T provides a secondary abnormality check for chest X-rays."
    )

    biovil_status = (
        "BioViL-T loaded ✅" if imaging_models.get("biovilt_available")
        else "BioViL-T not available — Gemini Vision only"
    )
    st.caption(f"Imaging backend: {biovil_status}")

    scan_files = st.file_uploader(
        "Upload scan images",
        accept_multiple_files=True,
        type=["jpg", "jpeg", "png", "bmp"],
        key="scan_uploader",
        label_visibility="collapsed",
    )

    if scan_files:
        st.write(f"{len(scan_files)} scan(s) selected:")
        for f in scan_files:
            detected = imaging.detect_modality(Path(f.name))
            st.caption(f"  🩻 {f.name}  ({f.size // 1024} KB) — detected: `{detected}`")

        if st.button("Ingest scans", type="primary", key="ingest_scans"):
            progress_bar = st.progress(0)
            scan_results = []
            for idx, f in enumerate(scan_files):
                tmp = Path(f"/content/scan_{f.name}")
                tmp.write_bytes(f.read())
                with st.spinner(f"Describing {f.name} with Gemini Vision..."):
                    r = imaging.ingest_scan(patient_id, tmp, models, imaging_models)
                scan_results.append(r)
                progress_bar.progress((idx + 1) / len(scan_files))

            st.success(f"✅ Processed {len(scan_results)} scan(s)")
            for r in scan_results:
                if r["status"] == "ok":
                    abnormal_label = " ⚠️ **ABNORMAL FLAGS**" if r["is_abnormal"] else ""
                    st.markdown(
                        f"✅ **{Path(r['file']).name}** — "
                        f"`{r['modality']}` | **{r['chunks']} chunk**{abnormal_label}"
                    )
                    if r["abnormal_flags"]:
                        st.warning(
                            "BioViL-T flagged: " + ", ".join(r["abnormal_flags"])
                        )
                    with st.expander("Gemini description"):
                        st.caption(r["gemini_description"])
                else:
                    st.error(f"❌ {Path(r['file']).name}: {r.get('reason', 'error')}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PATIENT VAULT
# ══════════════════════════════════════════════════════════════════════════════
with tab_vault:
    st.subheader(f"Patient Vault — `{patient_id}`")

    if st.button("🔄 Refresh vault", key="refresh_vault"):
        st.rerun()

    # Fetch all chunks for this patient
    result = collection.get(
        where={"patient_id": patient_id},
        include=["documents", "metadatas"],
    )

    if not result["ids"]:
        st.info(f"No documents ingested for patient `{patient_id}` yet. Go to the Upload tab.")
    else:
        metas = result["metadatas"]
        docs  = result["documents"]

        # ── Summary metrics ───────────────────────────────────────────────────
        by_file: dict[str, list] = {}
        sem_total: dict[str, int] = {}
        method_total: dict[str, int] = {}

        for text, meta in zip(docs, metas):
            fname = meta.get("file_name", "unknown")
            by_file.setdefault(fname, []).append((text, meta))
            s = meta.get("semantic_type", "unknown")
            m = meta.get("extraction_method", "unknown")
            sem_total[s]    = sem_total.get(s, 0) + 1
            method_total[m] = method_total.get(m, 0) + 1

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Documents",         len(by_file))
        c2.metric("Total chunks",      len(metas))
        c3.metric("Semantic types",    len(sem_total))
        c4.metric("DB total (all pts)", collection.count())

        # ── Semantic breakdown ────────────────────────────────────────────────
        st.divider()
        st.markdown("**Semantic type breakdown**")
        sem_cols = st.columns(max(len(sem_total), 1))
        for i, (sem, cnt) in enumerate(sorted(sem_total.items())):
            icon = SEMANTIC_ICONS.get(sem, "⬜")
            sem_cols[i % len(sem_cols)].metric(
                f"{icon} {sem.replace('_', ' ').title()}", cnt
            )

        # ── OCR method breakdown ──────────────────────────────────────────────
        st.markdown("**OCR method breakdown**")
        method_cols = st.columns(max(len(method_total), 1))
        for i, (method, cnt) in enumerate(sorted(method_total.items())):
            method_cols[i % len(method_cols)].metric(f"`{method}`", cnt)

        # ── Per-document expanders ────────────────────────────────────────────
        st.divider()
        st.markdown("**Documents**")

        for fname, file_chunks in sorted(by_file.items()):
            m0    = file_chunks[0][1]
            label = (
                f"📄 {fname}  —  `{m0.get('doc_type', '?')}`  |  "
                f"`{m0.get('extraction_method', '?')}`  |  "
                f"{len(file_chunks)} chunks  |  {m0.get('visit_date', 'no date')}"
            )
            with st.expander(label):
                info_cols = st.columns(2)
                with info_cols[0]:
                    if m0.get("doctor_name"): st.markdown(f"**Doctor:** {m0['doctor_name']}")
                    if m0.get("hospital"):    st.markdown(f"**Hospital:** {m0['hospital']}")
                    if m0.get("visit_date"):  st.markdown(f"**Date:** {m0['visit_date']}")
                with info_cols[1]:
                    if m0.get("diagnosis"):   st.markdown(f"**Diagnosis:** {m0['diagnosis']}")
                    if m0.get("drugs"):       st.markdown(f"**Drugs:** {m0['drugs']}")
                    if m0.get("surgery_type"): st.markdown(f"**Surgery:** {m0['surgery_type']}")

                st.markdown("---")
                st.markdown("**Chunks:**")

                # Build a lookup from file_name to (text, meta) pairs
                file_doc_metas = [
                    (t, cm) for t, cm in zip(docs, metas)
                    if cm.get("file_name") == fname
                ]
                # Sort by chunk_index
                file_doc_metas.sort(key=lambda x: x[1].get("chunk_index", 0))

                for text, cm in file_doc_metas:
                    sem  = cm.get("semantic_type", "unknown")
                    icon = SEMANTIC_ICONS.get(sem, "⬜")
                    st.markdown(
                        f"{icon} `{sem}` — chunk {cm.get('chunk_index', '?')}"
                    )
                    st.caption(text[:200] + ("..." if len(text) > 200 else ""))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ASK AI
# ══════════════════════════════════════════════════════════════════════════════
with tab_query:
    st.subheader(f"Ask AI — patient `{patient_id}`")

    with st.form("rag_form", clear_on_submit=False):
        question  = st.text_input(
            "",
            placeholder="e.g. What medications is this patient on?  /  Any history of lung disease?",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Ask →", type="primary")

    if submitted and question.strip():
        with st.spinner("Thinking..."):
            result = retrieval.rag_query(
                patient_id=patient_id,
                question=question.strip(),
                models=models,
            )

        # ── Answer ────────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(result["answer"])
        st.markdown("---")

        # ── Query trace ───────────────────────────────────────────────────────
        with st.expander("🔍 Query trace", expanded=False):
            st.markdown("**Original question**")
            st.code(question.strip(), language=None)

            st.markdown("**Normalised query** *(after typo correction + abbreviation expansion)*")
            if result["norm_query"] != question.strip():
                st.code(result["norm_query"], language=None)
            else:
                st.caption("No changes — query was already clean.")

            st.markdown("**Full prompt sent to Gemini**")
            st.code(result["prompt"], language=None)

        # ── Retrieved chunks ──────────────────────────────────────────────────
        st.markdown(f"**{result['chunk_count']} chunk(s) used to generate this answer**")

        for i, chunk in enumerate(result["sources"], 1):
            meta      = chunk["meta"]
            sem       = meta.get("semantic_type", "unknown")
            icon      = SEMANTIC_ICONS.get(sem, "⬜")
            doc_type  = meta.get("doc_type", "?")
            file_name = meta.get("file_name", "unknown")
            date_str  = meta.get("visit_date", "")

            rrf_score    = chunk.get("rrf_score", "—")
            rerank_score = chunk.get("rerank_score", None)
            score_label  = f"RRF `{rrf_score}`"
            if rerank_score is not None:
                score_label += f"  ·  rerank `{rerank_score}`"

            header = f"{icon} [{i}] **{file_name}** · `{doc_type}` / `{sem}`"
            if date_str:
                header += f" · {date_str}"
            header += f"  —  {score_label}"

            with st.expander(header, expanded=(i == 1)):

                # Chunk text
                st.markdown("**Extracted text**")
                st.markdown(
                    f"<div style='background:#f8f9fa;padding:10px;border-radius:6px;"
                    f"font-size:0.88em;line-height:1.5'>{chunk['text']}</div>",
                    unsafe_allow_html=True,
                )

                st.markdown("**Metadata**")

                # Scores row
                score_cols = st.columns(3)
                score_cols[0].metric("RRF score",    rrf_score)
                score_cols[1].metric("Rerank score", rerank_score if rerank_score is not None else "—")
                score_cols[2].metric("Vector score", chunk.get("score", "—"))

                # Document fields
                st.markdown("*Document*")
                doc_cols = st.columns(4)
                doc_cols[0].markdown(f"**File**  \n`{file_name}`")
                doc_cols[1].markdown(f"**Doc type**  \n`{doc_type}`")
                doc_cols[2].markdown(f"**Semantic type**  \n`{sem}`")
                doc_cols[3].markdown(f"**OCR method**  \n`{meta.get('extraction_method', '—')}`")

                # Clinical fields (only those present)
                clinical = {
                    "visit_date":   meta.get("visit_date"),
                    "doctor_name":  meta.get("doctor_name"),
                    "hospital":     meta.get("hospital"),
                    "diagnosis":    meta.get("diagnosis"),
                    "drugs":        meta.get("drugs"),
                    "surgery_type": meta.get("surgery_type"),
                    "modality":     meta.get("modality"),
                    "is_abnormal":  meta.get("is_abnormal"),
                }
                clinical = {k: v for k, v in clinical.items() if v}
                if clinical:
                    st.markdown("*Clinical*")
                    clin_cols = st.columns(min(len(clinical), 4))
                    for j, (k, v) in enumerate(clinical.items()):
                        clin_cols[j % 4].markdown(f"**{k.replace('_', ' ').title()}**  \n{v}")

                # Storage fields
                st.markdown("*Storage*")
                stor_cols = st.columns(4)
                stor_cols[0].markdown(f"**Chunk**  \n{meta.get('chunk_index', '?')} / {meta.get('total_chunks', '?')}")
                stor_cols[1].markdown(f"**Patient ID**  \n`{meta.get('patient_id', '—')}`")
                stor_cols[2].markdown(f"**Ingested**  \n{meta.get('ingested_at', '—')[:10]}")
                stor_cols[3].markdown(f"**BM25 score**  \n{chunk.get('bm25_score', '—')}")

    elif submitted:
        st.warning("Please enter a question.")
