"""
HeyDoc — shared vault component.
Used in both patient (self-view) and staff (clinical-review) contexts.
"""

import streamlit as st
from heydoc_theme import SEMANTIC, sem_pill, page_header, ocr_badge


def show_vault(collection, patient_id: str, clinical_mode: bool = False):
    """
    Render the full patient vault.

    Args:
        collection:    ChromaDB collection from models["collection"]
        patient_id:    patient to display
        clinical_mode: True = staff view (diagnosis + meds shown first, clinical framing)
                       False = patient view (chronological, personal framing)
    """
    result = collection.get(
        where={"patient_id": patient_id},
        include=["documents", "metadatas"],
    )

    if not result["ids"]:
        st.info(
            f"No documents found for patient `{patient_id}`. "
            + ("Ask the patient to upload their records first."
               if clinical_mode
               else "Go to **Upload Records** to add your first document.")
        )
        return

    docs  = result["documents"]
    metas = result["metadatas"]

    # ── Summary metrics ────────────────────────────────────────────────────────
    by_file:      dict[str, list] = {}
    sem_total:    dict[str, int]  = {}
    method_total: dict[str, int]  = {}

    for text, meta in zip(docs, metas):
        fname = meta.get("file_name", "unknown")
        by_file.setdefault(fname, []).append((text, meta))
        s = meta.get("semantic_type", "unknown")
        m = meta.get("extraction_method", "unknown")
        sem_total[s]    = sem_total.get(s, 0) + 1
        method_total[m] = method_total.get(m, 0) + 1

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Documents",    len(by_file))
    c2.metric("Total chunks", len(metas))
    c3.metric("Record types", len(sem_total))
    c4.metric("All patients (DB)", collection.count())

    # ── Semantic breakdown ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**Record categories**")

    # In clinical mode: prioritise diagnosis and medication_history
    priority = (["diagnosis", "medication_history"] if clinical_mode else [])
    ordered_sems = priority + [s for s in sem_total if s not in priority]

    cols = st.columns(max(len(ordered_sems), 1))
    for i, sem in enumerate(ordered_sems):
        cfg  = SEMANTIC.get(sem, {"icon": "•", "color": "#6B7280", "label": sem})
        cnt  = sem_total[sem]
        cols[i].markdown(
            f'<div style="text-align:center;padding:0.6rem;background:{SEMANTIC.get(sem,{}).get("bg","#F9FAFB")};'
            f'border-radius:10px;border:1px solid {SEMANTIC.get(sem,{}).get("border","#E5E7EB")}">'
            f'<div style="font-size:1.4rem">{cfg["icon"]}</div>'
            f'<div style="font-size:0.8rem;font-weight:600;color:{cfg["color"]}">{cfg["label"]}</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:#111827">{cnt}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── OCR method breakdown ───────────────────────────────────────────────────
    if not clinical_mode:
        st.markdown("**Extraction methods used**")
        method_cols = st.columns(max(len(method_total), 1))
        for i, (method, cnt) in enumerate(sorted(method_total.items())):
            method_cols[i].markdown(
                f'{ocr_badge(method)} <span style="font-size:0.8rem;color:#6B7280">{cnt} chunk(s)</span>',
                unsafe_allow_html=True,
            )

    # ── Per-document expanders ─────────────────────────────────────────────────
    st.markdown("---")
    heading = "**Clinical records**" if clinical_mode else "**Your documents**"
    st.markdown(heading)

    # In clinical mode, sort diagnosis-containing docs first
    def sort_key(fname):
        sems = [m.get("semantic_type","") for _, m in by_file[fname]]
        if clinical_mode:
            score = (0 if "diagnosis" in sems else 1 if "medication_history" in sems else 2)
            return (score, fname)
        return fname

    for fname in sorted(by_file, key=sort_key):
        file_chunks = by_file[fname]
        m0          = file_chunks[0][1]
        doc_sem     = m0.get("semantic_type", "unknown")
        sem_cfg     = SEMANTIC.get(doc_sem, {"icon": "📄", "color": "#6B7280", "label": doc_sem})

        label = (
            f"{sem_cfg['icon']} **{fname}**  ·  "
            f"`{m0.get('doc_type','?')}`  ·  "
            f"{len(file_chunks)} chunk(s)"
            + (f"  ·  {m0.get('visit_date','')}" if m0.get('visit_date') else "")
        )

        with st.expander(label, expanded=False):
            # Clinical fields row
            cf1, cf2, cf3, cf4 = st.columns(4)
            if m0.get("doctor_name"):  cf1.markdown(f"**Doctor**  \n{m0['doctor_name']}")
            if m0.get("hospital"):     cf2.markdown(f"**Hospital**  \n{m0['hospital']}")
            if m0.get("visit_date"):   cf3.markdown(f"**Date**  \n{m0['visit_date']}")
            cf4.markdown(f"**Method**  \n{ocr_badge(m0.get('extraction_method','?'))}", unsafe_allow_html=True)

            if m0.get("diagnosis"):
                st.markdown(
                    f'<div style="background:#FEF2F2;border-left:3px solid #DC2626;padding:0.4rem 0.75rem;border-radius:0 6px 6px 0;margin:0.5rem 0;font-size:0.87rem">'
                    f'🔴 <strong>Diagnosis:</strong> {m0["diagnosis"]}</div>',
                    unsafe_allow_html=True,
                )
            if m0.get("drugs"):
                st.markdown(
                    f'<div style="background:#EFF6FF;border-left:3px solid #2563EB;padding:0.4rem 0.75rem;border-radius:0 6px 6px 0;margin:0.5rem 0;font-size:0.87rem">'
                    f'💊 <strong>Medications:</strong> {m0["drugs"]}</div>',
                    unsafe_allow_html=True,
                )
            if m0.get("surgery_type"):
                st.markdown(
                    f'<div style="background:#FFF7ED;border-left:3px solid #EA580C;padding:0.4rem 0.75rem;border-radius:0 6px 6px 0;margin:0.5rem 0;font-size:0.87rem">'
                    f'⚕️ <strong>Surgery:</strong> {m0["surgery_type"]}</div>',
                    unsafe_allow_html=True,
                )
            if m0.get("abnormal_flags"):
                st.warning(f"⚠️ Imaging flag: {m0['abnormal_flags']}")

            # Chunks
            st.markdown("**Chunks**")
            file_doc_metas = sorted(
                [(t, cm) for t, cm in zip(docs, metas) if cm.get("file_name") == fname],
                key=lambda x: x[1].get("chunk_index", 0),
            )
            for text, cm in file_doc_metas:
                sem  = cm.get("semantic_type", "unknown")
                cfg  = SEMANTIC.get(sem, {"icon": "•", "color": "#6B7280", "bg": "#F9FAFB", "label": sem})
                st.markdown(
                    f'<div style="background:{cfg["bg"]};border:1px solid {cfg.get("border","#E5E7EB")};'
                    f'border-radius:8px;padding:0.5rem 0.75rem;margin:0.3rem 0;font-size:0.83rem">'
                    f'{sem_pill(sem)} '
                    f'<span style="color:#6B7280">chunk {cm.get("chunk_index","?")+1}/{cm.get("total_chunks","?")}</span><br>'
                    f'<span style="color:#374151">{text[:220]}{"…" if len(text)>220 else ""}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
