"""HeyDoc — all staff / doctor-facing views."""

import streamlit as st
from pathlib import Path

from heydoc_theme import inject_staff_css, page_header, sem_pill, SEMANTIC, STAFF_PRIMARY
from heydoc_vault import show_vault
from heydoc_mock import (
    mock_get_intake_data, get_queue, remove_from_queue,
    KNOWN_PATIENTS, DEPARTMENTS, DOCTORS,
)


# ── Sidebar nav ────────────────────────────────────────────────────────────────

def _sidebar():
    with st.sidebar:
        st.markdown(
            '<div style="font-size:1.6rem;font-weight:800;letter-spacing:-0.5px">🏥 HeyDoc</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="font-size:0.82rem;opacity:0.75;margin-bottom:0.1rem">'
            f'Staff: <strong>{st.session_state.user_name}</strong></div>',
            unsafe_allow_html=True,
        )
        selected = st.session_state.get("selected_patient")
        if selected:
            pname = KNOWN_PATIENTS.get(selected, selected)
            st.markdown(
                f'<div style="background:rgba(255,255,255,0.12);border-radius:6px;'
                f'padding:0.35rem 0.6rem;font-size:0.8rem;margin-bottom:0.75rem">'
                f'👤 {pname} · <span style="opacity:0.7">{selected}</span></div>',
                unsafe_allow_html=True,
            )

        st.markdown("---")
        st.markdown('<div style="font-size:0.7rem;opacity:0.45;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:0.4rem">Menu</div>', unsafe_allow_html=True)

        views = {
            "lookup":    "🔍  Patient Lookup",
            "summary":   "📋  Patient Summary",
            "intake":    "📝  Intake Form",
            "dashboard": "🏥  Queue Dashboard",
        }
        for key, label in views.items():
            active = st.session_state.get("view") == key
            if st.button(label, key=f"nav_{key}", use_container_width=True):
                st.session_state.view = key
                st.rerun()

        st.markdown("---")
        if st.button("Sign out", use_container_width=True):
            for k in ["role", "user_id", "user_name", "view", "selected_patient"]:
                st.session_state.pop(k, None)
            st.rerun()


# ── View 1: Patient Lookup ─────────────────────────────────────────────────────

def _show_lookup():
    page_header("Patient Lookup", "Search a patient by ID or select from known patients.")

    col_input, col_select = st.columns([1, 1], gap="large")

    with col_input:
        st.markdown("**Enter Patient ID directly**")
        pid_input = st.text_input("", placeholder="e.g. patient_001", label_visibility="collapsed")
        if st.button("Load patient →", type="primary", key="load_direct"):
            if pid_input.strip():
                st.session_state.selected_patient = pid_input.strip()
                st.session_state.view = "summary"
                st.rerun()
            else:
                st.warning("Please enter a patient ID.")

    with col_select:
        st.markdown("**Or pick from known patients**")
        options = ["—"] + [f"{pid} — {name}" for pid, name in KNOWN_PATIENTS.items()]
        chosen  = st.selectbox("", options, label_visibility="collapsed")
        if st.button("Select →", key="load_known"):
            if chosen != "—":
                pid = chosen.split(" — ")[0]
                st.session_state.selected_patient = pid
                st.session_state.view = "summary"
                st.rerun()

    # Recent lookups (session only)
    if st.session_state.get("selected_patient"):
        pid   = st.session_state.selected_patient
        pname = KNOWN_PATIENTS.get(pid, pid)
        st.markdown("---")
        st.markdown(f"**Currently loaded:** `{pid}` — {pname}")
        nav_cols = st.columns(3)
        if nav_cols[0].button("View records", use_container_width=True):
            st.session_state.view = "summary"
            st.rerun()
        if nav_cols[1].button("Intake form", use_container_width=True):
            st.session_state.view = "intake"
            st.rerun()


# ── View 2: Patient Summary (clinical mode vault) ──────────────────────────────

def _show_summary(models: dict):
    pid = st.session_state.get("selected_patient")
    if not pid:
        st.info("No patient selected. Go to **Patient Lookup** first.")
        return

    pname = KNOWN_PATIENTS.get(pid, pid)
    page_header(
        f"Patient Summary — {pname}",
        f"ID: {pid}  ·  Clinical view: diagnosis and medications shown first.",
    )

    # Prominent quick-action buttons
    qcol1, qcol2, _ = st.columns([1, 1, 2])
    if qcol1.button("📝 Generate intake form", use_container_width=True):
        st.session_state.view = "intake"
        st.rerun()
    if qcol2.button("🔍 Different patient", use_container_width=True):
        st.session_state.view = "lookup"
        st.rerun()

    st.markdown("---")
    show_vault(models["collection"], pid, clinical_mode=True)


# ── View 3: Intake Form ────────────────────────────────────────────────────────

def _show_intake(models: dict):
    pid = st.session_state.get("selected_patient")
    if not pid:
        st.info("No patient selected. Go to **Patient Lookup** first.")
        return

    pname = KNOWN_PATIENTS.get(pid, pid)
    page_header(
        "Intake Form",
        f"Pre-filled from stored records for {pname} ({pid}). "
        "Review every field before confirming — nothing is submitted automatically.",
    )

    # Load mock (swap for real auto-fill when Phase 5 backend is ready)
    if f"intake_data_{pid}" not in st.session_state:
        with st.spinner("Pre-filling from patient records…"):
            st.session_state[f"intake_data_{pid}"] = mock_get_intake_data(pid, models)
    data = st.session_state[f"intake_data_{pid}"]

    st.info(
        "📋 Fields below are pre-filled from stored documents. "
        "**Edit anything that looks wrong before confirming.**"
    )

    confirmed_key = f"intake_confirmed_{pid}"
    if st.session_state.get(confirmed_key):
        st.markdown(
            '<div class="confirm-banner">✅ Intake form confirmed and saved for this session. '
            'Hand off to the admissions desk.</div>',
            unsafe_allow_html=True,
        )
        if st.button("Edit again", key="edit_again"):
            st.session_state[confirmed_key] = False
            st.rerun()
        return

    with st.form("intake_form"):
        # ── Personal details ──────────────────────────────────────────────────
        st.markdown("#### Personal Details")
        pc1, pc2, pc3, pc4 = st.columns(4)
        name   = pc1.text_input("Full Name",    value=data.get("full_name", ""))
        age    = pc2.text_input("Age",           value=data.get("age", ""))
        gender = pc3.selectbox("Gender",         ["Male","Female","Other","Prefer not to say"],
                               index=["Male","Female","Other","Prefer not to say"].index(data.get("gender","Male")) if data.get("gender") in ["Male","Female","Other","Prefer not to say"] else 0)
        blood  = pc4.text_input("Blood Group",   value=data.get("blood_group",""))

        # ── Allergies ─────────────────────────────────────────────────────────
        st.markdown("#### Allergies")
        allergies = st.text_area(
            "Known allergies (one per line)",
            value="\n".join(data.get("allergies", [])),
            height=80,
        )

        # ── Current medications ───────────────────────────────────────────────
        st.markdown("#### Current Medications")
        meds = st.text_area(
            "Current medications (one per line)",
            value="\n".join(data.get("current_medications", [])),
            height=100,
        )

        # ── Past diagnoses ────────────────────────────────────────────────────
        st.markdown("#### Past Diagnoses")
        diagnoses = st.text_area(
            "Past diagnoses (one per line)",
            value="\n".join(data.get("past_diagnoses", [])),
            height=80,
        )

        # ── Surgical history ──────────────────────────────────────────────────
        st.markdown("#### Surgical History")
        surgeries = st.text_area(
            "Surgeries (one per line)",
            value="\n".join(data.get("surgical_history", [])),
            height=60,
        )

        # ── Insurance ────────────────────────────────────────────────────────
        st.markdown("#### Insurance")
        ins = data.get("insurance", {})
        ic1, ic2, ic3 = st.columns(3)
        ins_provider = ic1.text_input("Provider",    value=ins.get("provider",""))
        ins_policy   = ic2.text_input("Policy No.",  value=ins.get("policy_no",""))
        ins_valid    = ic3.text_input("Valid Till",  value=ins.get("valid_till",""))

        # ── Emergency contact ─────────────────────────────────────────────────
        st.markdown("#### Emergency Contact")
        ec = data.get("emergency_contact", {})
        ec1, ec2 = st.columns(2)
        ec_name  = ec1.text_input("Name",  value=ec.get("name",""))
        ec_phone = ec2.text_input("Phone", value=ec.get("phone",""))

        st.markdown("---")
        st.warning(
            "⚠️ **Review every field above before confirming.** "
            "Clicking Confirm submits this intake record for this session."
        )
        submitted = st.form_submit_button("✅ Confirm & finalise intake", type="primary")

    if submitted:
        # Persist back to session state (real backend would write to DB here)
        st.session_state[f"intake_data_{pid}"] = {
            **data,
            "full_name":           name,
            "age":                 age,
            "gender":              gender,
            "blood_group":         blood,
            "allergies":           [a.strip() for a in allergies.splitlines() if a.strip()],
            "current_medications": [m.strip() for m in meds.splitlines() if m.strip()],
            "past_diagnoses":      [d.strip() for d in diagnoses.splitlines() if d.strip()],
            "surgical_history":    [s.strip() for s in surgeries.splitlines() if s.strip()],
            "insurance": {"provider": ins_provider, "policy_no": ins_policy, "valid_till": ins_valid},
            "emergency_contact":   {"name": ec_name, "phone": ec_phone},
        }
        st.session_state[confirmed_key] = True
        st.rerun()


# ── View 4: Queue Dashboard ────────────────────────────────────────────────────

def _show_dashboard():
    page_header("Queue Dashboard", "Live check-in queue — shared with patient check-in view.")

    queue = get_queue()

    if st.button("🔄 Refresh", key="refresh_dash"):
        st.rerun()

    if not queue:
        st.info("No patients currently checked in.")
        return

    # Summary metrics
    waiting = sum(1 for e in queue if e["status"] == "waiting")
    active  = sum(1 for e in queue if e["status"] == "active")
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("In queue", len(queue))
    mc2.metric("Waiting",  waiting)
    mc3.metric("Active",   active)
    st.markdown("---")

    # Filter by department
    all_depts = sorted({e["department"] for e in queue})
    dept_filter = st.selectbox("Filter by department", ["All"] + all_depts, key="dept_filter")

    filtered = queue if dept_filter == "All" else [e for e in queue if e["department"] == dept_filter]

    for entry in filtered:
        status_label = {"active":"🟢 Active","waiting":"🟡 Waiting","done":"⚫ Done"}.get(entry["status"],"⚪")
        status_color = {"active":"#059669","waiting":"#D97706","done":"#6B7280"}.get(entry["status"],"#6B7280")

        with st.container():
            row_l, row_m, row_r = st.columns([3, 4, 2])
            with row_l:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:0.75rem">'
                    f'<div class="queue-pos">{entry["position"]}</div>'
                    f'<div><div style="font-weight:700;font-size:0.95rem">{entry["name"]}</div>'
                    f'<div style="font-size:0.78rem;color:#6B7280">{entry["patient_id"]} · Token {entry["token"]}</div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            with row_m:
                st.markdown(
                    f'<div style="font-size:0.85rem">'
                    f'<strong>{entry["department"]}</strong> · {entry["doctor"]}<br>'
                    f'Checked in: {entry["checked_in"]} · Wait: ~{entry["wait_minutes"]} min'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with row_r:
                st.markdown(
                    f'<div style="color:{status_color};font-weight:600;font-size:0.85rem">'
                    f'{status_label}</div>',
                    unsafe_allow_html=True,
                )
                if st.button("✓ Done", key=f"done_{entry['patient_id']}", use_container_width=True):
                    remove_from_queue(entry["patient_id"])
                    st.rerun()
            st.markdown('<div style="border-bottom:1px solid #F3F4F6;margin:0.4rem 0"></div>', unsafe_allow_html=True)


# ── Staff app entry point ──────────────────────────────────────────────────────

def show_staff_app(models: dict):
    inject_staff_css()
    _sidebar()

    view = st.session_state.get("view", "lookup")

    if view == "lookup":
        _show_lookup()
    elif view == "summary":
        _show_summary(models)
    elif view == "intake":
        _show_intake(models)
    elif view == "dashboard":
        _show_dashboard()
    else:
        _show_lookup()
