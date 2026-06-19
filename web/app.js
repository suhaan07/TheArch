/* ============================================================
   HeyDoc — vanilla JS port (no React, no build step)
   Mock data layer — replace with real API calls later.
   Every function here is the seam where the real backend plugs in.
   ============================================================ */
const MOCK = {
  patients: [
    { id: 'patient_001', name: 'Suhaan Aneja', dob: '2007-08-04', phone: '9910007330' },
    { id: 'patient_002', name: 'Ritika Sharma', dob: '1989-02-14', phone: '9876543210' },
    { id: 'patient_003', name: 'Mohammed Iqbal', dob: '1975-11-30', phone: '9123456780' },
  ],
  doctors: [
    { id: 'doctor_001', name: 'Dr. Sunil Choudhary', dept: 'Plastic Surgery', room: '304', hospital: 'Max Saket', timings: 'Mon-Fri 10:00-13:00' },
    { id: 'doctor_002', name: 'Dr. Anjali Rao', dept: 'Cardiology', room: '112', hospital: 'Max Saket', timings: 'Mon-Sat 09:00-12:00' },
  ],
  documents: {
    patient_001: [
      { id: 'd1', name: 'Discharge_Summary_16May.pdf', doc_type: 'discharge_summary', semantic_type: 'patient_information', uploaded_by: 'patient_001', date: '2026-05-17' },
      { id: 'd2', name: 'Prescription_Ceroxim.pdf', doc_type: 'prescription', semantic_type: 'medication_history', uploaded_by: 'patient_001', date: '2026-05-17' },
      { id: 'd3', name: 'Pus_CS_Report.pdf', doc_type: 'lab_report', semantic_type: 'lab_reports', uploaded_by: 'doctor_001', date: '2026-05-25' },
      { id: 'd4', name: 'Reexcision_Notes.pdf', doc_type: 'operative_notes', semantic_type: 'surgical_history', uploaded_by: 'doctor_001', date: '2026-05-16' },
    ],
    patient_002: [
      { id: 'd5', name: 'Lipid_Profile.pdf', doc_type: 'lab_report', semantic_type: 'lab_reports', uploaded_by: 'patient_002', date: '2026-04-02' },
    ],
    patient_003: [],
  },
  appointments: [
    { id: 'a1', patientId: 'patient_001', doctorId: 'doctor_001', time: '2026-06-18T15:30:00', type: 'follow_up', intakeStatus: 'verified' },
    { id: 'a2', patientId: 'patient_002', doctorId: 'doctor_002', time: '2026-06-18T16:00:00', type: 'admission', intakeStatus: 'pending' },
    { id: 'a3', patientId: 'patient_003', doctorId: 'doctor_001', time: '2026-06-18T16:30:00', type: 'new', intakeStatus: 'pending' },
  ],
  queue: [
    { appointmentId: 'a1', position: 1, status: 'waiting', checkedIn: true },
    { appointmentId: 'a2', position: 2, status: 'waiting', checkedIn: true },
    { appointmentId: 'a3', position: 3, status: 'not_checked_in', checkedIn: false },
  ],
  deptStatus: {
    patient_002: { insurance: 'approved', labs: 'pending', documentation: 'verified' },
    patient_003: { insurance: 'pending', labs: 'pending', documentation: 'pending' },
  },
};

const SEMANTIC = {
  patient_information: { label: 'Patient info', bg: '#e4e7e4', fg: '#3c4842' },
  diagnosis: { label: 'Diagnosis', bg: '#fbe4da', fg: '#a3401f' },
  medication_history: { label: 'Medication', bg: '#dcebfb', fg: '#1f5fa0' },
  lab_reports: { label: 'Lab report', bg: '#fbe8cc', fg: '#a3650e' },
  surgical_history: { label: 'Surgical', bg: '#eee4fb', fg: '#6a3fa0' },
  follow_up_notes: { label: 'Follow-up', bg: '#dcf2e9', fg: '#0f6e56' },
};

const ROLE_LABEL = {
  patient: 'Patient', doctor: 'Doctor', tpa: 'TPA / insurance desk', lab: 'Lab / diagnostics', admin: 'Hospital admin',
};

const API_BASE = 'http://localhost:8000';

const ICON_PATHS = {
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  upload: 'M12 16V4M12 4l-4 4M12 4l4 4M4 20h16',
  chat: 'M21 11.5a8.5 8.5 0 1 1-3.8-7.1L21 4l-1 4.5a8.5 8.5 0 0 1 1 3z',
  clock: 'M12 7v5l3 3M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z',
  calendar: 'M3 4h18v18H3zM16 2v4M8 2v4M3 10h18',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
  user: 'M20 21a8 8 0 1 0-16 0M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3',
  bell: 'M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0',
  check: 'M20 6 9 17l-5-5',
  plus: 'M12 5v14M5 12h14',
  stethoscope: 'M4 4v6a4 4 0 0 0 4 4h0a4 4 0 0 0 4-4V4M9 18a3 3 0 1 0 6 0v-4M19 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  shield: 'M12 2 4 5v6c0 5 4 9 8 11 4-2 8-6 8-11V5z',
  flask: 'M9 2v6L4 19a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-5-11V2M9 14h6',
  building: 'M3 21h18M5 21V7l7-4 7 4v14M9 9h1M9 13h1M14 9h1M14 13h1M9 21v-4h6v4',
  chevronRight: 'M9 18l6-6-6-6',
  arrowRight: 'M5 12h14M12 5l7 7-7 7',
  menu: 'M4 6h16M4 12h16M4 18h16',
  close: 'M18 6 6 18M6 6l12 12',
};

/* ============================================================
   Helpers
   ============================================================ */
function esc(str) {
  return String(str ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Safe to drop into a double-quoted onclick="..." attribute as a JS string literal.
function attrJson(value) {
  return esc(JSON.stringify(value));
}

function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}
function minsUntil(iso) {
  return Math.round((new Date(iso) - new Date()) / 60000);
}

function icon(name, size = 18, color = 'currentColor', cls = '') {
  const d = ICON_PATHS[name] || '';
  return `<span class="icon ${cls}" style="width:${size}px;height:${size}px;color:${color}">
    <svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>
  </span>`;
}

function badge(text, bg, fg) {
  return `<span class="badge" style="background:${bg};color:${fg}">${text}</span>`;
}

function semanticTag(type) {
  const s = SEMANTIC[type] || SEMANTIC.patient_information;
  return badge(s.label, s.bg, s.fg);
}

function docRow(d) {
  return `
    <div class="doc-row">
      ${icon('file', 17, 'var(--ink500)')}
      <div class="doc-row-body">
        <div class="doc-row-name">${esc(d.name)}</div>
        <div class="doc-row-date">${esc(d.date)}</div>
      </div>
      ${semanticTag(d.semantic_type)}
    </div>`;
}

function emptyState(iconName, title, sub) {
  return `
    <div class="empty-state">
      <div class="empty-state-icon">${icon(iconName, 22, 'var(--ink300)')}</div>
      <div class="empty-state-title">${esc(title)}</div>
      ${sub ? `<div class="empty-state-sub">${esc(sub)}</div>` : ''}
    </div>`;
}

function aiNotice() {
  return `
    <div class="ai-notice">
      ${icon('shield', 15, 'var(--amber600)')}
      <span>AI-assisted information, not a diagnosis. For any concern, please contact your doctor directly.</span>
    </div>`;
}

function pageHeader(title, sub) {
  return `
    <div class="page-header">
      <h1>${esc(title)}</h1>
      ${sub ? `<p>${esc(sub)}</p>` : ''}
    </div>`;
}

function statCard(iconName, label, value, sub, color) {
  return `
    <div class="card col">
      <div class="stat-card-head">
        <div class="stat-card-icon" style="background:${color}18">${icon(iconName, 16, color)}</div>
        <div class="stat-card-label">${esc(label)}</div>
      </div>
      <div class="stat-card-value">${value}</div>
      ${sub ? `<div class="stat-card-sub">${esc(sub)}</div>` : ''}
    </div>`;
}

function initials(name) {
  return name.split(' ').map(w => w[0]).join('').slice(0, 2);
}

/* ============================================================
   Global state
   ============================================================ */
const state = {
  user: null,           // { role, name, id }
  page: 'dashboard',
  auth: { mode: 'signin', step: 1, role: null, staffType: null, error: null, loading: false },
  ask: { messages: [] },
  booking: false,
  doctor: { selectedPatient: null },
  tpa: { selectedPatient: null },
  lab: { selectedPatient: null },
  uploadForPatient: { patientId: null },
  admin: { selected: null, verified: false, selectedPatient: null },
  sidebarOpen: false,
  documents: {},          // { [patientId]: Array<doc> } — populated by ensureDocuments()
  uploadStatus: {},        // { [contextKey]: {state, name, ...} } — upload progress/result
  patients: [],            // patients this doctor/tpa/lab is authorized to see — see ensurePatients()
  doctors: MOCK.doctors.slice(),    // real signed-up doctors merged in by ensureDoctors()
  appointments: {},        // { 'patient:<id>' | 'doctor:<id>': Array<appointment> }
  bookingError: null,
  queuePosition: null,     // { appointmentId, position, ahead_count, estimated_wait_minutes, is_current, estimated_call_time, drift_minutes }
  queueError: null,
  doctorDrift: null,       // minutes running behind (+) / ahead (-) schedule — null until ensureDoctorDrift() loads it
};

const CHECKIN_WINDOW_MINUTES = 30; // mirrors server.py's CHECKIN_WINDOW_MINUTES

/* ============================================================
   Real document storage + RAG chat — talks to server.py
   ============================================================ */
const _docsFetchedFor = new Set();

async function ensureDocuments(patientId, requester) {
  if (_docsFetchedFor.has(patientId)) return;
  _docsFetchedFor.add(patientId);
  try {
    let url = `${API_BASE}/documents/${patientId}`;
    if (requester) {
      const params = new URLSearchParams({ requester_id: requester.id, requester_role: requester.role });
      if (requester.hospital) params.set('requester_hospital', requester.hospital);
      url += `?${params}`;
    }
    const res = await fetch(url);
    if (res.status === 403) {
      state.documents[patientId] = { forbidden: true };
      render();
      return;
    }
    const rows = await res.json();
    state.documents[patientId] = rows.map(d => ({
      id: d.id,
      name: d.file_name,
      doc_type: d.doc_type,
      semantic_type: d.semantic_type,
      uploaded_by: d.uploaded_by,
      date: (d.uploaded_at || '').slice(0, 10),
    }));
  } catch (err) {
    state.documents[patientId] = [];
  }
  render();
}

function refreshDocuments(patientId) {
  _docsFetchedFor.delete(patientId);
  return ensureDocuments(patientId);
}

let _patientsFetched = false;
async function ensurePatients() {
  if (_patientsFetched) return;
  _patientsFetched = true;
  const role = state.user?.role;
  if (role !== 'doctor' && role !== 'tpa' && role !== 'lab' && role !== 'admin') return;
  try {
    // Doctors only see patients with an accepted appointment with them; TPA/lab/
    // admin (insurance desk, diagnostics, front desk/helpdesk) only see patients
    // with an accepted appointment with a doctor at their own hospital. No mock
    // fallback here — showing unauthorized patients (even demo ones) would
    // defeat the point of the restriction.
    const params = role === 'doctor'
      ? `doctor_id=${encodeURIComponent(state.user.id)}`
      : `hospital=${encodeURIComponent(state.user.hospital || '')}`;
    const res = await fetch(`${API_BASE}/patients?${params}`);
    state.patients = await res.json();
  } catch (err) {
    state.patients = []; // fail closed if the backend is unreachable
  }
  if (!state.patients.some(p => p.id === state.uploadForPatient.patientId)) {
    state.uploadForPatient.patientId = state.patients[0]?.id || null;
  }
  render();
}

let _doctorsFetched = false;
async function ensureDoctors() {
  if (_doctorsFetched) return;
  _doctorsFetched = true;
  try {
    const res = await fetch(`${API_BASE}/doctors`);
    const real = await res.json();
    const seen = new Set(real.map(d => d.id));
    state.doctors = [...real, ...MOCK.doctors.filter(d => !seen.has(d.id))];
  } catch (err) {
    // backend not running yet — keep the mock list so the UI still works
  }
  render();
}

const _apptsFetchedFor = new Set();
async function ensureAppointments(role, id) {
  const key = `${role}:${id}`;
  if (_apptsFetchedFor.has(key)) return;
  _apptsFetchedFor.add(key);
  try {
    const res = await fetch(`${API_BASE}/appointments?${role}_id=${encodeURIComponent(id)}`);
    state.appointments[key] = await res.json();
  } catch (err) {
    state.appointments[key] = [];
  }
  render();
}

function refreshAppointments(role, id) {
  _apptsFetchedFor.delete(`${role}:${id}`);
  return ensureAppointments(role, id);
}

// Single shared poll slot — only one queue-style page is ever visible at a
// time, so one timer is enough. Always stopPolling() before starting a new
// one so navigating away (or logging out) never leaves a stray timer running.
let _pollHandle = null;
function startPolling(fn, ms) {
  stopPolling();
  _pollHandle = setInterval(fn, ms);
}
function stopPolling() {
  if (_pollHandle) { clearInterval(_pollHandle); _pollHandle = null; }
}

// A real, honest "time waited" clock — ticks every second from checked_in_at,
// updating one DOM node directly rather than going through the full render()
// (re-rendering the whole app every second would be wasteful and flickery).
// Counts down to a target time (the scheduled slot adjusted by the doctor's
// running-early/late offset) — re-targets itself whenever the doctor changes
// that offset and a fresh poll brings in a new estimated_call_time.
let _tickHandle = null;
let _tickTarget = null;
function startCountdown(targetIso) {
  if (_tickTarget === targetIso && _tickHandle) return; // already counting down to this exact target
  stopTicking();
  _tickTarget = targetIso;
  const target = new Date(targetIso);
  const update = () => {
    const el = document.getElementById('queue-elapsed');
    if (!el) { stopTicking(); return; } // navigated away without nav()/logout() catching it
    const secs = Math.round((target - new Date()) / 1000);
    if (secs <= 0) { el.textContent = 'Any moment now'; return; }
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    el.textContent = h > 0
      ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
      : `${m}:${String(s).padStart(2, '0')}`;
  };
  update();
  _tickHandle = setInterval(update, 1000);
}
function stopTicking() {
  if (_tickHandle) { clearInterval(_tickHandle); _tickHandle = null; }
  _tickTarget = null;
}

async function bookAppointment(patientId, doctorId, time, type) {
  try {
    await apiCall('/appointments', { patient_id: patientId, doctor_id: doctorId, time, type });
    state.booking = false;
    state.bookingError = null;
    await refreshAppointments('patient', patientId);
  } catch (err) {
    state.bookingError = err.message;
    render();
  }
}

async function setAppointmentStatus(appointmentId, status, doctorId) {
  try {
    await apiCall(`/appointments/${appointmentId}/status`, { status });
    // Accepting grants access to a new patient — the cached authorized-patients
    // list (Upload for patient / Patient lookup dropdowns) must refresh right
    // away, not just on the doctor's next login.
    if (status === 'accepted') _patientsFetched = false;
    await refreshAppointments('doctor', doctorId);
  } catch (err) {
    state.bookingError = err.message;
    render();
  }
}

// ── Live queue (patient side) ──────────────────────────────────────────────
let _notifiedForAppt = null; // browser Notification should fire once per appointment, not every poll

function maybeNotifyNext(appointmentId, aheadCount) {
  if (aheadCount === null || aheadCount > 1) return;
  if (_notifiedForAppt === appointmentId) return;
  _notifiedForAppt = appointmentId;
  if (typeof Notification === 'undefined') return;
  const fire = () => new Notification('HeyDoc', { body: "You're next — please head to the clinic now." });
  if (Notification.permission === 'granted') fire();
  else if (Notification.permission !== 'denied') Notification.requestPermission().then(p => { if (p === 'granted') fire(); });
}

async function fetchQueuePosition(appointmentId) {
  try {
    const res = await fetch(`${API_BASE}/appointments/${appointmentId}/queue-position`);
    const data = await res.json();
    state.queuePosition = { appointmentId, ...data };
    maybeNotifyNext(appointmentId, data.ahead_count);
  } catch (err) {
    // transient network hiccup — keep showing the last known position
  }
  render();
}

const _queuePositionRequested = new Set();
function ensureQueuePosition(appointmentId) {
  if (_queuePositionRequested.has(appointmentId)) return;
  _queuePositionRequested.add(appointmentId);
  fetchQueuePosition(appointmentId);
}

async function checkInNow(appointmentId, patientId) {
  state.queueError = null;
  try {
    await apiCall(`/appointments/${appointmentId}/check-in`, {});
    await refreshAppointments('patient', patientId);
  } catch (err) {
    state.queueError = err.message;
    render();
  }
}

// ── Doctor "running early/late" drift — shifts every waiting patient's
// estimated call time at once, without touching anyone's booked slot. ──────
async function ensureDoctorDrift(doctorId) {
  if (state.doctorDrift !== null) return;
  try {
    const res = await fetch(`${API_BASE}/doctors/${doctorId}/drift`);
    const data = await res.json();
    state.doctorDrift = data.drift_minutes;
  } catch (err) {
    state.doctorDrift = 0;
  }
  render();
}

async function adjustDrift(doctorId, delta) {
  try {
    const res = await fetch(`${API_BASE}/doctors/${doctorId}/drift`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ delta_minutes: delta }),
    });
    const data = await res.json();
    state.doctorDrift = data.drift_minutes;
  } catch (err) {
    state.queueError = err.message;
  }
  render();
}

function uploadStatusHtml(status) {
  if (!status) return '';
  if (status.state === 'uploading') {
    return `<div class="dropzone-note">Uploading ${esc(status.name)} — running OCR/classification, this can take a moment…</div>`;
  }
  if (status.state === 'error') {
    return `<div class="dropzone-note" style="color:var(--coral600);background:var(--coral50)">Failed to ingest ${esc(status.name)}: ${esc(status.message)}</div>`;
  }
  if (status.state === 'done') {
    return `<div class="dropzone-note">${esc(status.name)} ingested as "${esc(status.doc_type)}" ✓</div>`;
  }
  return '';
}

async function uploadDocument(patientId, uploadedBy, file, statusKey) {
  const formData = new FormData();
  formData.append('patient_id', patientId);
  formData.append('uploaded_by', uploadedBy);
  if (state.user) {
    formData.append('requester_role', state.user.role);
    if (state.user.hospital) formData.append('requester_hospital', state.user.hospital);
  }
  formData.append('file', file);

  state.uploadStatus[statusKey] = { state: 'uploading', name: file.name };
  render();

  try {
    const res = await fetch(`${API_BASE}/documents/upload`, { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
    state.uploadStatus[statusKey] = { state: 'done', name: file.name, doc_type: data.doc_type };
    await refreshDocuments(patientId);
  } catch (err) {
    state.uploadStatus[statusKey] = { state: 'error', name: file.name, message: err.message };
    render();
  }
}

function handlePatientFiles(fileList) {
  Array.from(fileList || []).forEach(file =>
    uploadDocument(state.user.id, state.user.id, file, 'patientUpload')
  );
}

function handleStaffFile(fileList) {
  const file = (fileList || [])[0];
  if (!file) return;
  uploadDocument(state.uploadForPatient.patientId, state.user.id, file, 'staffUpload');
}

function render() {
  const root = document.getElementById('root');

  // render() can be triggered by an async callback (a fetch resolving in the
  // background) while the user is mid-typing into an uncontrolled input
  // anywhere on the page. Save + restore focus/value/cursor across the
  // innerHTML replacement so that doesn't wipe out what they typed.
  const active = document.activeElement;
  const isTextField = active && root.contains(active) && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA');
  const saved = isTextField
    ? { id: active.id, value: active.value, start: active.selectionStart, end: active.selectionEnd }
    : null;

  if (!state.user) {
    root.innerHTML = renderAuthScreen();
  } else {
    ensurePatients();
    ensureDoctors();
    const apps = { patient: renderPatientApp, doctor: renderDoctorApp, tpa: renderTpaApp, lab: renderLabApp, admin: renderAdminApp };
    const fn = apps[state.user.role] || renderPatientApp;
    root.innerHTML = fn();
  }

  if (saved && saved.id) {
    const el = document.getElementById(saved.id);
    if (el) {
      el.value = saved.value;
      el.focus();
      if (typeof el.setSelectionRange === 'function') {
        try { el.setSelectionRange(saved.start, saved.end); } catch (e) {}
      }
    }
  }
}

function nav(page) {
  stopPolling(); // the queue page (if any) restarts its own poll on render
  stopTicking();
  _queuePositionRequested.clear(); // re-fetch fresh every time a queue page is entered
  state.queueError = null;
  state.page = page;
  state.sidebarOpen = false;
  render();
}
function logout() {
  stopPolling();
  stopTicking();
  _queuePositionRequested.clear();
  state.user = null;
  state.page = 'dashboard';
  state.auth = { mode: 'signin', step: 1, role: null, staffType: null, error: null, loading: false };
  state.sidebarOpen = false;
  // Per-user caches must be invalidated on logout — otherwise signing back
  // in (even as a different user) within the same tab serves stale data
  // instead of refetching (e.g. an appointment's status change, or a doctor
  // who signed up after the directory was first fetched, wouldn't show).
  state.documents = {};
  state.appointments = {};
  state.queuePosition = null;
  state.queueError = null;
  state.doctorDrift = null;
  _docsFetchedFor.clear();
  _apptsFetchedFor.clear();
  _patientsFetched = false;
  _doctorsFetched = false;
  render();
}
function toggleSidebar() { state.sidebarOpen = !state.sidebarOpen; render(); }
function closeSidebar() { state.sidebarOpen = false; render(); }

/* ============================================================
   Shell (sidebar layout shared by every signed-in role)
   ============================================================ */
function shell(role, userName, navItems, active, contentHtml) {
  const navHtml = navItems.map(item => `
    <button class="nav-item ${active === item.key ? 'active' : ''}" onclick="nav('${item.key}')">
      ${icon(item.icon, 17)}
      ${esc(item.label)}
    </button>`).join('');
  const open = state.sidebarOpen;
  return `
    <div class="shell role-${role}">
      <div class="mobile-topbar">
        <button class="hamburger-btn" onclick="toggleSidebar()">${icon('menu', 22)}</button>
        <div class="logo">${icon('stethoscope', 17, '#fff')}</div>
        <div class="sidebar-brand-name">HeyDoc</div>
      </div>
      <div class="sidebar-backdrop ${open ? 'open' : ''}" onclick="closeSidebar()"></div>
      <div class="sidebar ${open ? 'open' : ''}">
        <button class="sidebar-close" onclick="closeSidebar()">${icon('close', 20)}</button>
        <div class="sidebar-brand">
          <div class="logo">${icon('stethoscope', 17, '#fff')}</div>
          <div class="sidebar-brand-name">HeyDoc</div>
        </div>
        <div class="sidebar-user">
          <div class="sidebar-avatar">${esc(initials(userName))}</div>
          <div style="min-width:0">
            <div class="sidebar-user-name">${esc(userName)}</div>
            <div class="sidebar-user-role">${esc(ROLE_LABEL[role])}</div>
          </div>
        </div>
        <div class="sidebar-nav">${navHtml}</div>
        <button class="sidebar-logout" onclick="logout()">${icon('logout', 17)} Sign out</button>
      </div>
      <div class="main-content">${contentHtml}</div>
    </div>`;
}

/* ============================================================
   AUTH — sign in / sign up with role selection
   ============================================================ */
function setAuthMode(m) { state.auth.mode = m; state.auth.step = 1; render(); }
function setAuthStep(s) { state.auth.step = s; render(); }
function chooseRole(key) { state.auth.role = key; state.auth.step = key === 'staff' ? 1.5 : 2; render(); }
function chooseStaffType(key) { state.auth.staffType = key; state.auth.step = 2; render(); }

function quickSignin(r) {
  const demoProfiles = {
    patient: { name: 'Suhaan Aneja', id: 'patient_001' },
    doctor: { name: 'Dr. Sunil Choudhary', id: 'doctor_001', dept: 'Plastic Surgery', room: '304', hospital: 'Max Saket', timings: 'Mon-Fri 10:00-13:00' },
    tpa: { name: 'Insurance desk', id: 'tpa_001', hospital: 'Max Saket' },
    lab: { name: 'Lab desk', id: 'lab_001', hospital: 'Max Saket' },
    admin: { name: 'Front desk admin', id: 'admin_001', hospital: 'Max Saket' },
  };
  state.user = { role: r, ...demoProfiles[r] };
  state.page = 'dashboard';
  render();
}

async function apiCall(path, body) {
  let res, data;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    data = await res.json();
  } catch (err) {
    throw new Error(`Could not reach the server at ${API_BASE} — is server.py running?`);
  }
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

async function signIn() {
  const email = document.getElementById('si-email')?.value.trim() || '';
  const password = document.getElementById('si-password')?.value || '';
  if (!email || !password) { state.auth.error = 'Enter your email and password.'; render(); return; }

  state.auth.loading = true; state.auth.error = null; render();
  try {
    const user = await apiCall('/signin', { email, password });
    state.user = user;
    state.page = 'dashboard';
    state.auth.loading = false;
    render();
  } catch (err) {
    state.auth.loading = false;
    state.auth.error = err.message;
    render();
  }
}

async function finishSignup() {
  const finalRole = state.auth.role === 'staff' ? state.auth.staffType : 'patient';
  const payload = {
    role: finalRole,
    name: document.getElementById('su-name')?.value.trim() || '',
    email: document.getElementById('su-email')?.value.trim() || '',
    password: document.getElementById('su-password')?.value || '',
    dept: document.getElementById('su-dept')?.value.trim() || null,
    room: document.getElementById('su-room')?.value.trim() || null,
    hospital: document.getElementById('su-hospital')?.value.trim() || null,
    timings: document.getElementById('su-timings')?.value.trim() || null,
  };
  if (!payload.name || !payload.email || !payload.password) {
    state.auth.error = 'Name, email, and password are required.';
    render();
    return;
  }

  state.auth.loading = true; state.auth.error = null; render();
  try {
    const user = await apiCall('/signup', payload);
    state.user = user;
    state.page = 'dashboard';
    state.auth.loading = false;
    render();
  } catch (err) {
    state.auth.loading = false;
    state.auth.error = err.message;
    render();
  }
}

function renderAuthScreen() {
  const { mode, step, role, staffType, error, loading } = state.auth;

  const roleCards = [
    { key: 'patient', icon: 'user', label: 'Patient', desc: 'Manage your own health records' },
    { key: 'staff', icon: 'building', label: 'Hospital staff', desc: 'Doctor, insurance, lab, or admin' },
  ];
  const staffCards = [
    { key: 'doctor', icon: 'stethoscope', label: 'Doctor', desc: 'Consultations, schedule, patient lookup' },
    { key: 'tpa', icon: 'shield', label: 'TPA / insurance desk', desc: 'Cashless claims, pre-authorization' },
    { key: 'lab', icon: 'flask', label: 'Lab / diagnostics', desc: 'Test results, scans, reports' },
    { key: 'admin', icon: 'building', label: 'Hospital admin', desc: 'Intake, admissions, front desk' },
  ];

  const errorHtml = error ? `<div class="auth-error">${esc(error)}</div>` : '';

  let body = '';
  if (mode === 'signin') {
    body = `
      ${errorHtml}
      <div class="field"><div class="field-label">Email</div><input class="input" type="email" placeholder="you@example.com" id="si-email"></div>
      <div class="field"><div class="field-label">Password</div><input class="input" type="password" placeholder="••••••••" id="si-password" onkeydown="if(event.key==='Enter') signIn()"></div>
      <button class="btn btn-primary btn-block" style="margin-top:4px" onclick="signIn()" ${loading ? 'disabled' : ''}>${loading ? 'Signing in…' : 'Sign in'}</button>
      <div class="quick-signin-label">Demo quick sign-in (no account needed)</div>
      <div class="quick-signin-row">
        ${Object.keys(ROLE_LABEL).map(r => `<button class="quick-signin-btn" onclick="quickSignin('${r}')">${esc(ROLE_LABEL[r])}</button>`).join('')}
      </div>`;
  } else if (mode === 'signup' && step === 1) {
    body = `
      <div class="field-label" style="margin-bottom:12px">I am signing up as a...</div>
      <div style="display:flex;flex-direction:column;gap:10px">
        ${roleCards.map(c => `
          <button class="role-card" onclick="chooseRole('${c.key}')">
            <div class="role-card-icon">${icon(c.icon, 19, 'var(--teal700)')}</div>
            <div style="flex:1">
              <div class="role-card-title">${esc(c.label)}</div>
              <div class="role-card-desc">${esc(c.desc)}</div>
            </div>
            ${icon('chevronRight', 16, 'var(--ink300)')}
          </button>`).join('')}
      </div>`;
  } else if (mode === 'signup' && step === 1.5) {
    body = `
      <button class="back-link" onclick="setAuthStep(1)">← back</button>
      <div class="field-label" style="margin-bottom:12px">Which team are you on?</div>
      <div class="grid-2">
        ${staffCards.map(c => `
          <button class="staff-card" onclick="chooseStaffType('${c.key}')">
            ${icon(c.icon, 19, 'var(--teal700)')}
            <div class="staff-card-title">${esc(c.label)}</div>
            <div class="staff-card-desc">${esc(c.desc)}</div>
          </button>`).join('')}
      </div>`;
  } else if (mode === 'signup' && step === 2) {
    let extra = '';
    if (staffType === 'doctor') {
      extra = `
        <div class="field"><div class="field-label">Department / specialty</div><input class="input" placeholder="e.g. Cardiology" id="su-dept"></div>
        <div style="display:flex;gap:12px">
          <div style="flex:1" class="field"><div class="field-label">Room</div><input class="input" placeholder="304" id="su-room"></div>
          <div style="flex:1" class="field"><div class="field-label">Hospital</div><input class="input" placeholder="Max Saket" id="su-hospital"></div>
        </div>
        <div class="field"><div class="field-label">Available timings</div><input class="input" placeholder="Mon-Fri 10:00-13:00" id="su-timings"></div>`;
    } else if (staffType === 'tpa' || staffType === 'lab' || staffType === 'admin') {
      extra = `<div class="field"><div class="field-label">Hospital / organization</div><input class="input" placeholder="Max Saket" id="su-hospital"></div>`;
    }
    body = `
      <button class="back-link" onclick="setAuthStep(${role === 'staff' ? 1.5 : 1})">← back</button>
      ${errorHtml}
      <div class="field"><div class="field-label">Full name</div><input class="input" placeholder="Jane Doe" id="su-name"></div>
      <div class="field"><div class="field-label">Email</div><input class="input" type="email" placeholder="you@example.com" id="su-email"></div>
      <div class="field"><div class="field-label">Password</div><input class="input" type="password" placeholder="•••••••• (min 6 characters)" id="su-password"></div>
      ${extra}
      <button class="btn btn-primary btn-block" style="margin-top:8px" onclick="finishSignup()" ${loading ? 'disabled' : ''}>${loading ? 'Creating account…' : 'Create account'}</button>`;
  }

  return `
    <div class="auth-wrap">
      <div class="auth-inner">
        <div class="auth-header">
          <div class="logo lg">${icon('stethoscope', 29, '#fff')}</div>
          <div class="auth-title">HeyDoc</div>
          <div class="auth-sub">Your medical history, remembered.</div>
        </div>
        <div class="card">
          <div class="auth-tabs">
            <button class="auth-tab ${mode === 'signin' ? 'active' : ''}" onclick="setAuthMode('signin')">Sign in</button>
            <button class="auth-tab ${mode === 'signup' ? 'active' : ''}" onclick="setAuthMode('signup')">Sign up</button>
          </div>
          ${body}
        </div>
      </div>
    </div>`;
}

/* ============================================================
   PATIENT — Dashboard / Upload / Ask / Appointments / Queue
   ============================================================ */
function renderPatientApp() {
  const user = state.user;
  if (state.documents[user.id] === undefined) ensureDocuments(user.id);
  const docs = state.documents[user.id] || [];
  const myDocs = docs.filter(d => d.uploaded_by === user.id);
  const careTeamDocs = docs.filter(d => d.uploaded_by !== user.id);
  if (state.appointments[`patient:${user.id}`] === undefined) ensureAppointments('patient', user.id);
  const myAppts = state.appointments[`patient:${user.id}`] || [];

  const navItems = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'upload', label: 'Upload documents', icon: 'upload' },
    { key: 'ask', label: 'Ask HeyDoc', icon: 'chat' },
    { key: 'appointments', label: 'Appointments', icon: 'calendar' },
    { key: 'queue', label: 'My queue', icon: 'clock' },
  ];

  let content = '';
  if (state.page === 'dashboard') content = renderPatientDashboard(docs, myAppts);
  else if (state.page === 'upload') content = renderPatientUpload(myDocs, careTeamDocs);
  else if (state.page === 'ask') content = renderAskHeyDoc(user.id);
  else if (state.page === 'appointments') content = renderPatientAppointments(myAppts);
  else if (state.page === 'queue') content = renderPatientQueue(myAppts);

  return shell('patient', user.name, navItems, state.page, content);
}

function renderPatientDashboard(docs, appts) {
  const meds = docs.filter(d => d.semantic_type === 'medication_history').length;
  const next = appts[0];
  return `
    ${pageHeader('Welcome back', 'Your personal health memory assistant.')}
    <div class="row mb-20">
      ${statCard('file', 'Documents', docs.length, 'medical records stored', 'var(--teal600)')}
      ${statCard('user', 'Medication chunks', meds, 'from your records', 'var(--blue600)')}
      ${statCard('calendar', 'Appointments', appts.length, 'upcoming & past', 'var(--coral600)')}
    </div>
    <div class="row">
      <div class="card col-1-3">
        <div class="flex-center-gap mb-10">${icon('chat', 18, 'var(--teal600)')}<div style="font-weight:700;font-size:15px">Ask HeyDoc</div></div>
        <p style="font-size:13.5px;color:var(--ink500);line-height:1.6;margin:0 0 14px">
          Ask natural-language questions about your health history. Answers are grounded in your uploaded records, with sources cited.
        </p>
        <button class="btn btn-primary" onclick="nav('ask')">Start conversation ${icon('arrowRight', 14, '#fff')}</button>
      </div>
      <div class="card col">
        <div style="font-weight:700;font-size:15px;margin-bottom:12px">Next appointment</div>
        ${next ? `
          <div>
            <div style="font-size:14px;font-weight:600;color:var(--ink900)">${fmtTime(next.time)} · ${esc(new Date(next.time).toLocaleDateString())}</div>
            <div style="font-size:13px;color:var(--ink500);margin-top:2px">${esc(next.doctor_name || '')}</div>
            <div style="display:flex;gap:6px;margin-top:8px">
              ${badge(next.type === 'admission' ? 'Admission' : next.type === 'new' ? 'New patient' : 'Follow-up', 'var(--teal50)', 'var(--teal700)')}
              ${badge(next.status, next.status === 'accepted' ? 'var(--teal100)' : next.status === 'declined' ? 'var(--coral100)' : 'var(--amber100)', next.status === 'accepted' ? 'var(--teal700)' : next.status === 'declined' ? 'var(--coral600)' : 'var(--amber600)')}
            </div>
          </div>` : emptyState('calendar', 'No upcoming appointments')}
      </div>
    </div>`;
}

function renderPatientUpload(myDocs, careTeamDocs) {
  const status = state.uploadStatus.patientUpload;
  return `
    ${pageHeader('Upload documents', 'HeyDoc will OCR, classify, and chunk your records automatically.')}
    <div class="card dropzone mb-24" ondragover="event.preventDefault()" ondrop="event.preventDefault();handlePatientFiles(event.dataTransfer.files)">
      ${icon('upload', 26, 'var(--teal600)')}
      <div class="dropzone-title">Drag &amp; drop medical documents here</div>
      <div class="dropzone-sub">Supports PDF, PNG, JPG, TXT up to 10MB</div>
      <input type="file" id="patient-file-input" style="display:none" onchange="handlePatientFiles(this.files)">
      <button class="btn btn-secondary" style="margin-top:14px" onclick="document.getElementById('patient-file-input').click()">Select files</button>
      ${uploadStatusHtml(status)}
    </div>

    <div class="section-title">Your uploads</div>
    <div class="card mb-24">
      ${myDocs.length ? myDocs.map(docRow).join('') : emptyState('file', 'No documents uploaded yet')}
    </div>

    <div class="section-title">Documents from your care team</div>
    <p class="section-sub">Scans, reports, and results uploaded by your doctor, lab, or insurance desk.</p>
    <div class="card">
      ${careTeamDocs.length ? careTeamDocs.map(docRow).join('') : emptyState('file', 'Nothing here yet')}
    </div>`;
}

async function sendAsk(presetText) {
  const inputEl = document.getElementById('ask-input');
  const text = presetText !== undefined ? presetText : (inputEl ? inputEl.value : '');
  if (!text || !text.trim()) return;
  state.ask.messages.push({ role: 'user', text });
  if (inputEl) inputEl.value = '';
  render();

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patient_id: state.user.id, question: text }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Chat request failed');
    state.ask.messages.push({
      role: 'assistant',
      text: data.answer,
      sources: data.sources,
      confidence: data.confidence,
      verified: data.verified,
    });
  } catch (err) {
    state.ask.messages.push({
      role: 'assistant',
      text: `Could not reach HeyDoc's RAG backend (${err.message}). Is server.py running with GEMINI_API_KEY set?`,
    });
  }
  render();
  const el = document.getElementById('ask-input');
  if (el) el.focus();
}
function askKeydown(e) { if (e.key === 'Enter') sendAsk(); }

function renderAskHeyDoc() {
  const messages = state.ask.messages;
  const suggestions = ['What medications am I currently on?', 'Summarize my recent lab reports', 'What was I prescribed after my surgery?', 'When was my last follow-up?'];
  let body;
  if (!messages.length) {
    body = `
      <div style="padding:20px 0">
        ${emptyState('chat', 'How can I help you today?', 'Ask about medications, diagnoses, lab results, or anything from your records.')}
        <div class="chat-suggestions">
          ${suggestions.map(s => `<button class="chat-suggestion" onclick="sendAsk(${attrJson(s)})">${esc(s)}</button>`).join('')}
        </div>
      </div>`;
  } else {
    body = `<div class="chat-messages">
      ${messages.map(m => `
        <div class="chat-msg ${m.role}">
          <div class="chat-bubble ${m.role}">${esc(m.text)}</div>
          ${m.sources && m.sources.length ? `<div class="chat-sources">${m.sources.map(s => badge(`${icon('file', 11)} ${esc(s.name)}`, 'var(--ink100)', 'var(--ink700)')).join('')}</div>` : ''}
          ${m.role === 'assistant' && m.confidence !== undefined ? `<div style="font-size:11.5px;color:var(--ink500);margin-top:6px">Confidence: ${m.confidence}% · ${m.verified ? 'verified against records' : 'not fully verified'}</div>` : ''}
          ${m.role === 'assistant' ? aiNotice() : ''}
        </div>`).join('')}
    </div>`;
  }
  return `
    ${pageHeader('Ask HeyDoc', 'Answers are grounded in your uploaded records, with sources cited.')}
    <div class="card chat-card">
      <div class="chat-body">${body}</div>
      <div class="chat-input-row">
        <input class="input" id="ask-input" placeholder="Ask about your medical history..." onkeydown="askKeydown(event)">
        <button class="btn btn-primary" onclick="sendAsk()">${icon('arrowRight', 15, '#fff')}</button>
      </div>
    </div>`;
}

function toggleBooking() { state.booking = !state.booking; state.bookingError = null; render(); }

function confirmBooking() {
  const doctorId = document.getElementById('book-doctor')?.value;
  const date = document.getElementById('book-date')?.value;
  const time = document.getElementById('book-time')?.value;
  const visitType = document.getElementById('book-type')?.value;
  if (!doctorId || !date || !time) {
    state.bookingError = 'Please choose a doctor, date, and time.';
    render();
    return;
  }
  const type = visitType === 'Hospital admission' ? 'admission' : 'follow_up';
  bookAppointment(state.user.id, doctorId, `${date}T${time}:00`, type);
}

function renderPatientAppointments(appts) {
  const booking = state.booking;
  const error = state.bookingError;
  return `
    ${pageHeader('Appointments', 'Schedule visits and complete pre-admission formalities before you arrive.')}
    <button class="btn btn-primary mb-20" onclick="toggleBooking()">${icon('plus', 15, '#fff')} Book appointment</button>

    ${booking ? `
      <div class="card mb-20">
        ${error ? `<div class="auth-error">${esc(error)}</div>` : ''}
        <div class="field"><div class="field-label">Doctor</div>
          <select class="input" id="book-doctor">${state.doctors.map(d => `<option value="${d.id}">${esc(d.name)} — ${esc(d.dept || '')}${d.timings ? ` (${esc(d.timings)})` : ''}</option>`).join('')}</select>
        </div>
        <div style="display:flex;gap:12px">
          <div style="flex:1" class="field"><div class="field-label">Date</div><input class="input" type="date" id="book-date"></div>
          <div style="flex:1" class="field"><div class="field-label">Time</div><input class="input" type="time" id="book-time"></div>
        </div>
        <div class="field"><div class="field-label">Visit type</div>
          <select class="input" id="book-type"><option>OPD consultation</option><option>Hospital admission</option></select>
        </div>
        <button class="btn btn-primary" onclick="confirmBooking()">Confirm booking</button>
      </div>` : ''}

    ${appts.length ? appts.map(a => {
      const isAdmission = a.type === 'admission';
      return `
        <div class="card mb-14">
          <div class="appt-card-head">
            <div>
              <div class="appt-doctor">${esc(a.doctor_name || '')}</div>
              <div class="appt-meta">${esc(a.dept || '')} · Room ${esc(a.room || '')} · ${fmtTime(a.time)} · ${esc(new Date(a.time).toLocaleDateString())}</div>
            </div>
            <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end">
              ${badge(isAdmission ? 'Admission' : a.type === 'new' ? 'New patient' : 'Follow-up', isAdmission ? 'var(--coral100)' : 'var(--teal100)', isAdmission ? 'var(--coral600)' : 'var(--teal700)')}
              ${badge(a.status, a.status === 'accepted' ? 'var(--teal100)' : a.status === 'declined' ? 'var(--coral100)' : 'var(--amber100)', a.status === 'accepted' ? 'var(--teal700)' : a.status === 'declined' ? 'var(--coral600)' : 'var(--amber600)')}
            </div>
          </div>
          ${isAdmission ? `
            <div class="preadmit">
              <div class="preadmit-title">Pre-admission formalities</div>
              ${[{ label: 'Insurance verification', done: true }, { label: 'Documentation review', done: true }, { label: 'Payment', done: false }].map(s => `
                <div class="preadmit-step">
                  <div class="preadmit-dot ${s.done ? 'done' : ''}">${s.done ? icon('check', 11, '#fff') : ''}</div>
                  <span style="color:${s.done ? 'var(--ink900)' : 'var(--ink500)'}">${esc(s.label)}</span>
                </div>`).join('')}
              <p class="preadmit-note">Complete these before arrival so you skip the front-desk queue.</p>
            </div>` : ''}
        </div>`;
    }).join('') : emptyState('calendar', 'No appointments yet', 'Book one above to get started.')}`;
}

function renderPatientQueue(appts) {
  const next = appts.find(a => a.status === 'checked_in' || a.status === 'in_consultation')
    || appts.find(a => a.status === 'accepted')
    || null;

  if (!next) {
    stopPolling();
    stopTicking();
    return `${pageHeader('My queue', 'Check in and track your live position.')}<div class="card">${emptyState('calendar', 'No upcoming appointments', 'Book an accepted appointment to use digital check-in.')}</div>`;
  }

  const isLive = next.status === 'checked_in' || next.status === 'in_consultation';
  let box;

  if (isLive) {
    if (!_pollHandle) startPolling(() => fetchQueuePosition(next.id), 15000);
    ensureQueuePosition(next.id);
    const pos = state.queuePosition && state.queuePosition.appointmentId === next.id ? state.queuePosition : null;
    const countdown = pos && pos.estimated_call_time
      ? `<div class="queue-elapsed">Estimated call in <span id="queue-elapsed">0:00</span></div>` : '';
    const driftNote = pos && pos.drift_minutes
      ? `<div class="queue-elapsed">${pos.drift_minutes > 0 ? `Doctor is running ${pos.drift_minutes} min behind schedule` : `Doctor is running ${-pos.drift_minutes} min ahead of schedule`}</div>` : '';

    if (pos && pos.estimated_call_time) startCountdown(pos.estimated_call_time);

    if (!pos) {
      box = `<div class="queue-wait-box">${icon('clock', 20, 'var(--ink500)')}<div style="font-weight:600;font-size:13.5px;margin-top:8px">Loading your position…</div></div>`;
    } else if (pos.is_current) {
      box = `
        <div class="queue-checked-box">
          <div class="queue-checked-label">You're up now</div>
          <div class="queue-eta">the doctor has called you in</div>
        </div>`;
    } else {
      const upNext = pos.ahead_count <= 1;
      box = `
        <div class="queue-checked-box" style="${upNext ? 'background:var(--amber50)' : ''}">
          <div class="queue-checked-label" style="${upNext ? 'color:var(--amber600)' : ''}">${upNext ? "You're next — head to the clinic now" : "You're checked in"}</div>
          <div class="queue-position" style="${upNext ? 'color:var(--amber600)' : ''}">#${pos.position}</div>
          <div class="queue-eta">${pos.ahead_count} ahead · est. wait ~${pos.estimated_wait_minutes} min</div>
          ${countdown}
          ${driftNote}
        </div>`;
    }
  } else {
    stopPolling();
    stopTicking();
    const mins = minsUntil(next.time);
    const checkInOpen = mins <= CHECKIN_WINDOW_MINUTES;
    if (!checkInOpen) {
      box = `
        <div class="queue-wait-box">
          ${icon('clock', 20, 'var(--ink500)')}
          <div style="font-weight:600;font-size:13.5px;margin-top:8px">Check-in opens ${CHECKIN_WINDOW_MINUTES} minutes before your appointment</div>
          <div style="font-size:12.5px;color:var(--ink500);margin-top:2px">Opens in ${mins - CHECKIN_WINDOW_MINUTES} min</div>
        </div>`;
    } else {
      box = `<button class="btn btn-primary btn-block" onclick="checkInNow('${next.id}','${state.user.id}')">Check in now</button>`;
    }
  }

  return `
    ${pageHeader('My queue', 'Check in and track your live position in real time.')}
    ${state.queueError ? `<div class="auth-error mb-14">${esc(state.queueError)}</div>` : ''}
    <div class="card">
      <div style="font-weight:700;font-size:15px;margin-bottom:4px">${esc(next.doctor_name || '')}</div>
      <div style="font-size:13px;color:var(--ink500);margin-bottom:18px">${fmtTime(next.time)} · ${esc(new Date(next.time).toLocaleDateString())}</div>
      ${box}
    </div>`;
}

/* ============================================================
   Shared vault view + "upload for patient" (doctor/tpa/lab)
   ============================================================ */
function vaultView(patientId, emphasize) {
  if (state.documents[patientId] === undefined) {
    ensureDocuments(patientId, state.user);
    return emptyState('file', 'Loading records…');
  }
  const docs = state.documents[patientId];
  if (docs && docs.forbidden) {
    return emptyState(
      'shield',
      'No access to this patient',
      state.user.role === 'doctor'
        ? "You don't have an accepted appointment with this patient."
        : "This patient isn't under a doctor at your hospital."
    );
  }
  const order = emphasize
    ? ['diagnosis', 'medication_history', 'lab_reports', 'surgical_history', 'follow_up_notes', 'patient_information']
    : Object.keys(SEMANTIC);
  const grouped = order.map(t => ({ type: t, docs: docs.filter(d => d.semantic_type === t) })).filter(g => g.docs.length);
  if (!docs.length) return emptyState('file', 'No records for this patient yet');
  return grouped.map(g => `
    <div style="margin-bottom:18px">
      <div style="margin-bottom:8px">${semanticTag(g.type)}</div>
      ${g.docs.map(docRow).join('')}
    </div>`).join('');
}

function setUploadForPatientId(id) { state.uploadForPatient.patientId = id; render(); }

function uploadForPatient(role) {
  const { patientId } = state.uploadForPatient;
  const status = state.uploadStatus.staffUpload;
  if (!state.patients.length) {
    const why = role === 'doctor'
      ? "You don't have any patients yet — accept an appointment request first."
      : "You don't have any patients yet — this list only shows patients with an accepted appointment with a doctor at your hospital.";
    return `<div class="card">${emptyState('user', 'No patients yet', why)}</div>`;
  }
  return `
    <div class="card">
      <div class="field"><div class="field-label">Patient</div>
        <select class="input" onchange="setUploadForPatientId(this.value)">
          ${state.patients.map(p => `<option value="${p.id}" ${p.id === patientId ? 'selected' : ''}>${esc(p.name)} (${p.id})</option>`).join('')}
        </select>
      </div>
      <div class="dropzone compact">
        ${icon('upload', 22, 'var(--teal600)')}
        <div class="dropzone-title">Upload on behalf of this patient</div>
        <input type="file" id="staff-file-input" style="display:none" onchange="handleStaffFile(this.files)">
        <button class="btn btn-secondary" style="margin-top:12px" onclick="document.getElementById('staff-file-input').click()">Select file</button>
      </div>
      ${uploadStatusHtml(status)}
    </div>`;
}

/* ============================================================
   DOCTOR
   ============================================================ */
function setDoctorSelectedPatient(id) { state.doctor.selectedPatient = id; render(); }
function goToLookup(patientId) { state.doctor.selectedPatient = patientId; state.page = 'lookup'; render(); }
function goToUploadFor(patientId) { state.uploadForPatient.patientId = patientId; state.page = 'upload'; render(); }

function renderDoctorApp() {
  const user = state.user;
  if (state.appointments[`doctor:${user.id}`] === undefined) ensureAppointments('doctor', user.id);
  const myAppts = state.appointments[`doctor:${user.id}`] || [];
  const doc = { dept: user.dept || '', room: user.room || '', hospital: user.hospital || '', timings: user.timings || '' };

  const navItems = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'schedule', label: 'My schedule', icon: 'calendar' },
    { key: 'queue', label: 'Patient queue', icon: 'clock' },
    { key: 'lookup', label: 'Patient lookup', icon: 'search' },
    { key: 'upload', label: 'Upload for patient', icon: 'upload' },
  ];

  let content = '';
  if (state.page === 'dashboard') {
    const pending = myAppts.filter(a => a.status === 'pending');
    content = `
      ${pageHeader(`Good afternoon, ${user.name}`, `${doc.dept} · Room ${doc.room} · ${doc.hospital}`)}
      <div class="row mb-20">
        ${statCard('clock', 'Pending requests', pending.length, '', 'var(--amber600)')}
        ${statCard('calendar', 'Appointments', myAppts.length, '', 'var(--teal600)')}
        ${statCard('user', 'New patients', myAppts.filter(a => a.type === 'new').length, '', 'var(--coral600)')}
      </div>
      <div style="font-weight:700;font-size:15px;margin-bottom:10px">Appointment requests</div>
      ${myAppts.length ? myAppts.map(a => `
          <div class="card mb-10 flex-between">
            <div>
              <div style="font-weight:600;font-size:14px">${esc(a.patient_name || '')}</div>
              <div style="font-size:12.5px;color:var(--ink500)">${fmtTime(a.time)} · ${esc(new Date(a.time).toLocaleDateString())} · ${a.type === 'new' ? 'New patient' : a.type === 'admission' ? 'Admission' : 'Follow-up'}</div>
            </div>
            <div style="display:flex;gap:8px;align-items:center">
              ${badge(a.status, a.status === 'accepted' ? 'var(--teal100)' : a.status === 'declined' ? 'var(--coral100)' : 'var(--amber100)', a.status === 'accepted' ? 'var(--teal700)' : a.status === 'declined' ? 'var(--coral600)' : 'var(--amber600)')}
              ${a.status === 'pending' ? `
                <button class="btn btn-secondary" onclick="setAppointmentStatus('${a.id}','accepted','${user.id}')">Accept</button>
                <button class="btn btn-ghost" onclick="setAppointmentStatus('${a.id}','declined','${user.id}')">Decline</button>
              ` : `
                <button class="btn btn-secondary" onclick="goToLookup('${a.patient_id}')">View vault</button>
                <button class="btn btn-secondary" onclick="goToUploadFor('${a.patient_id}')">Upload</button>
              `}
            </div>
          </div>`).join('') : emptyState('calendar', 'No appointment requests yet')}`;
  } else if (state.page === 'schedule') {
    content = `
      ${pageHeader('My schedule', 'Edit your availability — patients book against these slots.')}
      <div class="card">
        <div class="field"><div class="field-label">Department</div><input class="input" value="${esc(doc.dept)}"></div>
        <div style="display:flex;gap:12px">
          <div style="flex:1" class="field"><div class="field-label">Room</div><input class="input" value="${esc(doc.room)}"></div>
          <div style="flex:1" class="field"><div class="field-label">Hospital</div><input class="input" value="${esc(doc.hospital)}"></div>
        </div>
        <div class="field"><div class="field-label">Available timings</div><input class="input" value="${esc(doc.timings)}"></div>
        <button class="btn btn-primary">Save changes</button>
      </div>`;
  } else if (state.page === 'queue') {
    const inQueue = myAppts.filter(a => a.status === 'checked_in' || a.status === 'in_consultation')
      .sort((a, b) => new Date(a.time) - new Date(b.time));
    const waiting = myAppts.filter(a => a.status === 'accepted')
      .sort((a, b) => new Date(a.time) - new Date(b.time));

    if (inQueue.length) { if (!_pollHandle) startPolling(() => refreshAppointments('doctor', user.id), 15000); }
    else stopPolling();

    if (state.doctorDrift === null) ensureDoctorDrift(user.id);
    const drift = state.doctorDrift;
    const driftLabel = drift === null ? 'Loading…'
      : drift === 0 ? 'Running on schedule'
      : drift > 0 ? `Running ${drift} min behind` : `Running ${-drift} min ahead`;

    content = `
      ${pageHeader('Patient queue', 'Checked-in patients, in slot order.')}
      <div class="card mb-20 flex-between">
        <div>
          <div style="font-weight:700;font-size:14px">${esc(driftLabel)}</div>
          <div style="font-size:12px;color:var(--ink500);margin-top:2px">Running early or behind today? Adjust here — every waiting patient's estimate updates right away.</div>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-ghost" onclick="adjustDrift('${user.id}', -5)">−5 min</button>
          <button class="btn btn-ghost" onclick="adjustDrift('${user.id}', 5)">+5 min</button>
        </div>
      </div>
      ${inQueue.length ? inQueue.map((a, i) => {
          const current = a.status === 'in_consultation';
          return `
            <div class="card mb-10 queue-row" style="${current ? 'border-color:var(--teal600);background:var(--teal50)' : ''}">
              <div class="queue-row-num" style="${current ? 'background:var(--teal600);color:#fff' : ''}">${i + 1}</div>
              <div style="flex:1">
                <div style="font-weight:600;font-size:14px">${esc(a.patient_name || '')}</div>
                <div style="font-size:12.5px;color:var(--ink500)">${fmtTime(a.time)} · ${a.type === 'new' ? 'New patient' : a.type === 'admission' ? 'Admission' : 'Follow-up'} · ${current ? 'in consultation' : 'checked in'}</div>
              </div>
              <button class="btn btn-secondary" onclick="goToLookup('${a.patient_id}')">View vault</button>
              ${current
                ? `<button class="btn btn-primary" onclick="setAppointmentStatus('${a.id}','completed','${user.id}')">Mark complete</button>`
                : `<button class="btn btn-primary" onclick="setAppointmentStatus('${a.id}','in_consultation','${user.id}')">Start consultation</button>
                   <button class="btn btn-ghost" onclick="setAppointmentStatus('${a.id}','no_show','${user.id}')">No-show</button>`}
            </div>`;
        }).join('') : emptyState('clock', 'No one checked in yet', 'Patients show up here once they check in for an accepted appointment.')}

      ${waiting.length ? `
        <div class="section-title" style="margin-top:24px">Accepted — waiting for check-in</div>
        ${waiting.map(a => `
          <div class="card mb-10 queue-row">
            <div style="flex:1">
              <div style="font-weight:600;font-size:14px">${esc(a.patient_name || '')}</div>
              <div style="font-size:12.5px;color:var(--ink500)">${fmtTime(a.time)} · ${esc(new Date(a.time).toLocaleDateString())}</div>
            </div>
            ${badge('not checked in', 'var(--ink100)', 'var(--ink500)')}
          </div>`).join('')}` : ''}`;
  } else if (state.page === 'lookup') {
    const selected = state.doctor.selectedPatient;
    content = `
      ${pageHeader('Patient lookup', "Search a patient to view their full vault.")}
      <div class="field"><div class="field-label">Patient</div>
        <select class="input" onchange="setDoctorSelectedPatient(this.value)">
          <option value="" ${!selected ? 'selected' : ''}>Select a patient...</option>
          ${state.patients.map(p => `<option value="${p.id}" ${p.id === selected ? 'selected' : ''}>${esc(p.name)} (${p.id})</option>`).join('')}
        </select>
      </div>
      ${selected ? vaultView(selected, true) : ''}`;
  } else if (state.page === 'upload') {
    content = `${pageHeader('Upload for patient', "Add a scan, report, or note directly to a patient's vault.")}${uploadForPatient('doctor')}`;
  }

  return shell('doctor', user.name, navItems, state.page, content);
}

/* ============================================================
   TPA / Insurance desk
   ============================================================ */
function setTpaSelectedPatient(id) { state.tpa.selectedPatient = id; render(); }

function renderTpaApp() {
  const user = state.user;
  const navItems = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'lookup', label: 'Patient lookup', icon: 'search' },
    { key: 'upload', label: 'Upload for patient', icon: 'upload' },
    { key: 'claims', label: 'Claims tracker', icon: 'shield' },
  ];
  const claimPatients = Object.keys(MOCK.deptStatus);

  let content = '';
  if (state.page === 'dashboard') {
    content = `
      ${pageHeader('Insurance desk', 'Coordinate cashless claims and pre-authorization.')}
      <div class="row">
        ${statCard('shield', 'Pending pre-auth', claimPatients.filter(p => MOCK.deptStatus[p].insurance === 'pending').length, '', 'var(--amber600)')}
        ${statCard('check', 'Approved', claimPatients.filter(p => MOCK.deptStatus[p].insurance === 'approved').length, '', 'var(--teal600)')}
      </div>`;
  } else if (state.page === 'lookup') {
    const selected = state.tpa.selectedPatient;
    content = `
      ${pageHeader('Patient lookup')}
      <div class="field"><div class="field-label">Patient</div>
        <select class="input" onchange="setTpaSelectedPatient(this.value)">
          <option value="" ${!selected ? 'selected' : ''}>Select a patient...</option>
          ${state.patients.map(p => `<option value="${p.id}" ${p.id === selected ? 'selected' : ''}>${esc(p.name)} (${p.id})</option>`).join('')}
        </select>
      </div>
      ${selected ? vaultView(selected, false) : ''}`;
  } else if (state.page === 'upload') {
    content = `${pageHeader('Upload for patient', 'Insurance documents, pre-auth letters, claim paperwork.')}${uploadForPatient('tpa')}`;
  } else if (state.page === 'claims') {
    content = `
      ${pageHeader('Claims tracker')}
      ${claimPatients.map(pid => {
        const p = MOCK.patients.find(pt => pt.id === pid);
        const s = MOCK.deptStatus[pid].insurance;
        return `
          <div class="card mb-10 flex-between">
            <div style="font-weight:600;font-size:14px">${esc(p?.name || '')}</div>
            ${badge(s, s === 'approved' ? 'var(--teal100)' : 'var(--amber100)', s === 'approved' ? 'var(--teal700)' : 'var(--amber600)')}
          </div>`;
      }).join('')}`;
  }

  return shell('tpa', user.name, navItems, state.page, content);
}

/* ============================================================
   Lab / diagnostics
   ============================================================ */
function setLabSelectedPatient(id) { state.lab.selectedPatient = id; render(); }

function renderLabApp() {
  const user = state.user;
  const navItems = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'lookup', label: 'Patient lookup', icon: 'search' },
    { key: 'upload', label: 'Upload results', icon: 'upload' },
    { key: 'pending', label: 'Pending work', icon: 'clock' },
  ];
  const pending = Object.entries(MOCK.deptStatus).filter(([, s]) => s.labs === 'pending');

  let content = '';
  if (state.page === 'dashboard') {
    content = `
      ${pageHeader('Lab / diagnostics', 'Upload test results and scans for processing.')}
      ${statCard('flask', 'Pending orders', pending.length, '', '#6a3fa0')}`;
  } else if (state.page === 'lookup') {
    const selected = state.lab.selectedPatient;
    content = `
      ${pageHeader('Patient lookup')}
      <div class="field"><div class="field-label">Patient</div>
        <select class="input" onchange="setLabSelectedPatient(this.value)">
          <option value="" ${!selected ? 'selected' : ''}>Select a patient...</option>
          ${state.patients.map(p => `<option value="${p.id}" ${p.id === selected ? 'selected' : ''}>${esc(p.name)} (${p.id})</option>`).join('')}
        </select>
      </div>
      ${selected ? vaultView(selected, false) : ''}`;
  } else if (state.page === 'upload') {
    content = `${pageHeader('Upload test results', 'Reports go through ingestion. Scan images go through imaging.ingest_scan with Gemini Vision + BioViL-T flagging.')}${uploadForPatient('lab')}`;
  } else if (state.page === 'pending') {
    content = `
      ${pageHeader('Pending work')}
      ${pending.map(([pid]) => {
        const p = MOCK.patients.find(pt => pt.id === pid);
        return `<div class="card mb-10"><div style="font-weight:600;font-size:14px">${esc(p?.name || '')}</div><div style="font-size:12.5px;color:var(--ink500)">Awaiting upload</div></div>`;
      }).join('')}
      ${!pending.length ? emptyState('check', 'Nothing pending') : ''}`;
  }

  return shell('lab', user.name, navItems, state.page, content);
}

/* ============================================================
   Hospital admin
   ============================================================ */
function openIntakeForm(apptId) {
  state.admin.selected = MOCK.appointments.find(a => a.id === apptId);
  state.admin.verified = false;
  state.page = 'intake';
  render();
}
function selectIntakeArrival(apptId) {
  state.admin.selected = apptId ? MOCK.appointments.find(a => a.id === apptId) : null;
  state.admin.verified = false;
  render();
}
function setVerified(checked) { state.admin.verified = checked; render(); }

function intakeForm(appt) {
  const p = MOCK.patients.find(pt => pt.id === appt.patientId);
  const status = MOCK.deptStatus[appt.patientId] || { insurance: 'pending', labs: 'pending', documentation: 'pending' };
  const verified = state.admin.verified;
  return `
    <div class="card mb-16">
      <div style="font-weight:700;font-size:15px;margin-bottom:14px">Cross-department status</div>
      <div class="dept-status-row">
        ${Object.entries(status).map(([dept, s]) => `
          <div class="dept-status-cell">
            <div class="dept-status-label">${esc(dept)}</div>
            ${badge(s, (s === 'approved' || s === 'verified') ? 'var(--teal100)' : 'var(--amber100)', (s === 'approved' || s === 'verified') ? 'var(--teal700)' : 'var(--amber600)')}
          </div>`).join('')}
      </div>
    </div>
    <div class="card">
      <div style="font-weight:700;font-size:15px;margin-bottom:14px">Admission summary — ${esc(p?.name || '')}</div>
      <div class="field"><div class="field-label">Allergies (from vault)</div><input class="input" value="Penicillin — noted in 2024 discharge summary"></div>
      <div class="field"><div class="field-label">Current medications (from vault)</div><input class="input" value="Ceroxim-XP 625mg, Pantop 40mg"></div>
      <div class="field"><div class="field-label">Insurance details</div><input class="input" value="Star Health — Policy #SH2024118832"></div>
      <div class="field"><div class="field-label">Past diagnoses</div><input class="input" value="Recurrent dermoid cyst, nasal tip"></div>
      <div class="verify-box">
        <input type="checkbox" class="verify-checkbox" ${verified ? 'checked' : ''} onchange="setVerified(this.checked)">
        <span>I have reviewed every field above against the source documents</span>
      </div>
      <button class="btn btn-primary mt-8" ${!verified ? 'disabled' : ''}>Verify and confirm admission</button>
      <p style="font-size:11.5px;color:var(--ink500);margin-top:8px">Nothing is finalized automatically — this requires explicit human confirmation.</p>
    </div>`;
}

function setAdminSelectedPatient(id) { state.admin.selectedPatient = id; render(); }

function renderAdminApp() {
  const user = state.user;
  const navItems = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'intake', label: 'Intake forms', icon: 'file' },
    { key: 'admissions', label: "Today's arrivals", icon: 'calendar' },
    { key: 'lookup', label: 'Patient lookup', icon: 'search' },
    { key: 'upload', label: 'Upload for patient', icon: 'upload' },
  ];
  const admissions = MOCK.appointments.filter(a => a.type === 'admission' || a.type === 'new');

  let content = '';
  if (state.page === 'dashboard') {
    content = `
      ${pageHeader('Front desk', 'Hospital intake automation — generate, verify, confirm.')}
      <div class="row mb-20">
        ${statCard('calendar', "Today's arrivals", admissions.length, '', 'var(--coral600)')}
        ${statCard('clock', 'Pending verification', admissions.filter(a => a.intakeStatus === 'pending').length, '', 'var(--amber600)')}
      </div>`;
  } else if (state.page === 'admissions') {
    content = `
      ${pageHeader("Today's arrivals")}
      ${admissions.map(a => {
        const p = MOCK.patients.find(pt => pt.id === a.patientId);
        return `
          <div class="card mb-10 flex-between">
            <div>
              <div style="font-weight:600;font-size:14px">${esc(p?.name || '')}</div>
              <div style="font-size:12.5px;color:var(--ink500)">${fmtTime(a.time)} · ${esc(a.type)}</div>
            </div>
            <button class="btn btn-secondary" onclick="openIntakeForm('${a.id}')">Open intake form</button>
          </div>`;
      }).join('')}`;
  } else if (state.page === 'intake') {
    const selected = state.admin.selected;
    content = `
      ${pageHeader('Intake form', "Pre-filled from the patient's vault. Review every field before confirming.")}
      ${!selected ? `
        <div class="field"><div class="field-label">Select arrival</div>
          <select class="input" onchange="selectIntakeArrival(this.value)">
            <option value="">Choose a patient...</option>
            ${admissions.map(a => `<option value="${a.id}">${esc(MOCK.patients.find(p => p.id === a.patientId)?.name || '')}</option>`).join('')}
          </select>
        </div>` : intakeForm(selected)}`;
  } else if (state.page === 'lookup') {
    const selectedPatient = state.admin.selectedPatient;
    content = `
      ${pageHeader('Patient lookup', "Search a patient to view their full vault.")}
      <div class="field"><div class="field-label">Patient</div>
        <select class="input" onchange="setAdminSelectedPatient(this.value)">
          <option value="" ${!selectedPatient ? 'selected' : ''}>Select a patient...</option>
          ${state.patients.map(p => `<option value="${p.id}" ${p.id === selectedPatient ? 'selected' : ''}>${esc(p.name)} (${p.id})</option>`).join('')}
        </select>
      </div>
      ${selectedPatient ? vaultView(selectedPatient, false) : ''}`;
  } else if (state.page === 'upload') {
    content = `${pageHeader('Upload for patient', "Add a scan, report, or note directly to a patient's vault.")}${uploadForPatient('admin')}`;
  }

  return shell('admin', user.name, navItems, state.page, content);
}

/* ============================================================
   Init
   ============================================================ */
render();
