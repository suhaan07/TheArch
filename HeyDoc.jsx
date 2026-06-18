import React, { useState, useMemo } from 'react';

/* ============================================================
   HeyDoc — Design tokens
   ============================================================ */
const T = {
  teal900: '#0a3d33', teal700: '#0f6e56', teal600: '#16876b', teal500: '#1d9e75',
  teal100: '#dcf2e9', teal50: '#f1f9f6',
  coral600: '#c4502c', coral500: '#d85a30', coral100: '#fbe4da', coral50: '#fdf2ec',
  ink900: '#1c2420', ink700: '#3c4842', ink500: '#6b756f', ink300: '#a6ada8', ink100: '#e4e7e4',
  cream: '#faf8f3', white: '#ffffff',
  amber600: '#a3650e', amber100: '#fbe8cc', amber50: '#fdf4e6',
  blue600: '#1f5fa0', blue100: '#dcebfb', blue50: '#eef6fd',
};

const SEMANTIC = {
  patient_information: { label: 'Patient info',       bg: '#e4e7e4', fg: '#3c4842' },
  diagnosis:            { label: 'Diagnosis',           bg: '#fbe4da', fg: '#a3401f' },
  medication_history:   { label: 'Medication',          bg: '#dcebfb', fg: '#1f5fa0' },
  lab_reports:           { label: 'Lab report',          bg: '#fbe8cc', fg: '#a3650e' },
  surgical_history:      { label: 'Surgical',             bg: '#eee4fb', fg: '#6a3fa0' },
  follow_up_notes:       { label: 'Follow-up',            bg: '#dcf2e9', fg: '#0f6e56' },
};

const ROLE_COLOR = {
  patient: T.teal600, doctor: T.blue600, tpa: T.amber600, lab: '#6a3fa0', admin: T.coral600,
};
const ROLE_LABEL = {
  patient: 'Patient', doctor: 'Doctor', tpa: 'TPA / insurance desk', lab: 'Lab / diagnostics', admin: 'Hospital admin',
};

/* ============================================================
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

function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}
function minsUntil(iso) {
  return Math.round((new Date(iso) - new Date('2026-06-18T15:05:00')) / 60000);
}

/* ============================================================
   Shared primitives
   ============================================================ */
function Icon({ name, size = 18, color = 'currentColor' }) {
  const paths = {
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
  };
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={paths[name] || ''} />
    </svg>
  );
}

function Logo({ size = 28 }) {
  return (
    <div style={{ width: size, height: size, borderRadius: 8, background: T.teal600, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      <Icon name="stethoscope" size={size * 0.6} color="#fff" />
    </div>
  );
}

function Badge({ children, bg, fg }) {
  return (
    <span style={{ background: bg, color: fg, fontSize: 12, fontWeight: 600, padding: '3px 9px', borderRadius: 999, whiteSpace: 'nowrap' }}>
      {children}
    </span>
  );
}

function Card({ children, style }) {
  return (
    <div style={{ background: T.white, border: `1px solid ${T.ink100}`, borderRadius: 14, padding: '20px 22px', ...style }}>
      {children}
    </div>
  );
}

function Button({ children, onClick, variant = 'primary', style, type = 'button', disabled }) {
  const base = { border: 'none', borderRadius: 10, padding: '10px 18px', fontSize: 14, fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8, transition: 'opacity .15s', opacity: disabled ? 0.5 : 1 };
  const variants = {
    primary: { background: T.teal600, color: '#fff' },
    secondary: { background: T.teal50, color: T.teal700, border: `1px solid ${T.teal100}` },
    ghost: { background: 'transparent', color: T.ink700, border: `1px solid ${T.ink100}` },
    danger: { background: T.coral500, color: '#fff' },
  };
  return (
    <button type={type} disabled={disabled} onClick={onClick} style={{ ...base, ...variants[variant], ...style }}>
      {children}
    </button>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: 'block', marginBottom: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: T.ink700, marginBottom: 6 }}>{label}</div>
      {children}
    </label>
  );
}

const inputStyle = {
  width: '100%', boxSizing: 'border-box', padding: '10px 12px', borderRadius: 10,
  border: `1px solid ${T.ink100}`, fontSize: 14, background: T.cream, outline: 'none',
};

function SemanticTag({ type }) {
  const s = SEMANTIC[type] || SEMANTIC.patient_information;
  return <Badge bg={s.bg} fg={s.fg}>{s.label}</Badge>;
}

function EmptyState({ icon, title, sub }) {
  return (
    <div style={{ textAlign: 'center', padding: '48px 20px', color: T.ink500 }}>
      <div style={{ width: 48, height: 48, borderRadius: 12, background: T.cream, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px' }}>
        <Icon name={icon} size={22} color={T.ink300} />
      </div>
      <div style={{ fontWeight: 600, color: T.ink700, marginBottom: 4 }}>{title}</div>
      {sub && <div style={{ fontSize: 13 }}>{sub}</div>}
    </div>
  );
}

function AiNotice() {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', background: T.amber50, border: `1px solid ${T.amber100}`, borderRadius: 10, padding: '10px 14px', fontSize: 12.5, color: T.amber600, marginTop: 14 }}>
      <Icon name="shield" size={15} color={T.amber600} />
      <span>AI-assisted information, not a diagnosis. For any concern, please contact your doctor directly.</span>
    </div>
  );
}

/* ============================================================
   Sidebar shell (shared layout for every signed-in role)
   ============================================================ */
function Shell({ role, userName, nav, active, onNav, onLogout, children }) {
  return (
    <div style={{ display: 'flex', minHeight: 640, background: T.cream, fontFamily: '-apple-system, "Segoe UI", Roboto, sans-serif', borderRadius: 16, overflow: 'hidden', border: `1px solid ${T.ink100}` }}>
      <div style={{ width: 240, background: T.white, borderRight: `1px solid ${T.ink100}`, display: 'flex', flexDirection: 'column', padding: '20px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 8px 22px' }}>
          <Logo />
          <div style={{ fontSize: 18, fontWeight: 700, color: T.ink900 }}>HeyDoc</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 10px', marginBottom: 18, background: T.cream, borderRadius: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: '50%', background: ROLE_COLOR[role], color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700 }}>
            {userName.split(' ').map(w => w[0]).join('').slice(0,2)}
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.ink900, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{userName}</div>
            <div style={{ fontSize: 11.5, color: ROLE_COLOR[role], fontWeight: 600 }}>{ROLE_LABEL[role]}</div>
          </div>
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {nav.map(item => (
            <button key={item.key} onClick={() => onNav(item.key)} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 10,
              border: 'none', background: active === item.key ? ROLE_COLOR[role] : 'transparent',
              color: active === item.key ? '#fff' : T.ink700, fontSize: 14, fontWeight: 600,
              cursor: 'pointer', textAlign: 'left', width: '100%',
            }}>
              <Icon name={item.icon} size={17} color={active === item.key ? '#fff' : T.ink500} />
              {item.label}
            </button>
          ))}
        </div>
        <button onClick={onLogout} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 10, border: 'none', background: 'transparent', color: T.ink500, fontSize: 14, fontWeight: 600, cursor: 'pointer', marginTop: 12 }}>
          <Icon name="logout" size={17} />
          Sign out
        </button>
      </div>
      <div style={{ flex: 1, padding: '28px 36px', overflowY: 'auto' }}>
        {children}
      </div>
    </div>
  );
}

function PageHeader({ title, sub }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, color: T.ink900, margin: 0 }}>{title}</h1>
      {sub && <p style={{ fontSize: 14, color: T.ink500, margin: '6px 0 0' }}>{sub}</p>}
    </div>
  );
}

/* ============================================================
   AUTH — sign in / sign up with role selection
   ============================================================ */
function AuthScreen({ onSignedIn }) {
  const [mode, setMode] = useState('signin');
  const [step, setStep] = useState(1);
  const [role, setRole] = useState(null);
  const [staffType, setStaffType] = useState(null);
  const [form, setForm] = useState({ name: '', email: '', password: '', dept: '', room: '', hospital: '', timings: '' });

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

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

  function finishSignup() {
    const finalRole = role === 'staff' ? staffType : 'patient';
    onSignedIn({ role: finalRole, name: form.name || 'New user', id: `${finalRole}_${Math.floor(Math.random()*900+100)}` });
  }

  function quickSignin(r) {
    const names = { patient: 'Suhaan Aneja', doctor: 'Dr. Sunil Choudhary', tpa: 'Insurance desk', lab: 'Lab desk', admin: 'Front desk admin' };
    onSignedIn({ role: r, name: names[r], id: r === 'patient' ? 'patient_001' : `${r}_001` });
  }

  return (
    <div style={{ minHeight: 640, background: T.cream, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: '-apple-system, "Segoe UI", Roboto, sans-serif', padding: 32, borderRadius: 16 }}>
      <div style={{ width: 460 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 28 }}>
          <Logo size={48} />
          <div style={{ fontSize: 26, fontWeight: 700, color: T.ink900, marginTop: 14 }}>HeyDoc</div>
          <div style={{ fontSize: 14, color: T.ink500, marginTop: 4 }}>Your medical history, remembered.</div>
        </div>

        <Card>
          <div style={{ display: 'flex', gap: 4, marginBottom: 22, background: T.cream, borderRadius: 10, padding: 4 }}>
            {['signin', 'signup'].map(m => (
              <button key={m} onClick={() => { setMode(m); setStep(1); }} style={{
                flex: 1, padding: '8px 0', border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer',
                background: mode === m ? T.white : 'transparent', color: mode === m ? T.teal700 : T.ink500,
              }}>
                {m === 'signin' ? 'Sign in' : 'Sign up'}
              </button>
            ))}
          </div>

          {mode === 'signin' && (
            <>
              <Field label="Email">
                <input style={inputStyle} type="email" placeholder="you@example.com" value={form.email} onChange={e => set('email', e.target.value)} />
              </Field>
              <Field label="Password">
                <input style={inputStyle} type="password" placeholder="••••••••" value={form.password} onChange={e => set('password', e.target.value)} />
              </Field>
              <Button style={{ width: '100%', justifyContent: 'center', marginTop: 4 }} onClick={() => quickSignin('patient')}>
                Sign in
              </Button>
              <div style={{ fontSize: 12, color: T.ink500, textAlign: 'center', margin: '16px 0 10px' }}>Demo quick sign-in</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center' }}>
                {Object.keys(ROLE_LABEL).map(r => (
                  <button key={r} onClick={() => quickSignin(r)} style={{ fontSize: 12, fontWeight: 600, padding: '6px 10px', borderRadius: 8, border: `1px solid ${T.ink100}`, background: T.cream, color: T.ink700, cursor: 'pointer' }}>
                    {ROLE_LABEL[r]}
                  </button>
                ))}
              </div>
            </>
          )}

          {mode === 'signup' && step === 1 && (
            <>
              <div style={{ fontSize: 13, fontWeight: 600, color: T.ink700, marginBottom: 12 }}>I am signing up as a...</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {roleCards.map(c => (
                  <button key={c.key} onClick={() => { setRole(c.key); setStep(c.key === 'staff' ? 1.5 : 2); }} style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px', borderRadius: 12,
                    border: `1px solid ${T.ink100}`, background: T.white, cursor: 'pointer', textAlign: 'left',
                  }}>
                    <div style={{ width: 38, height: 38, borderRadius: 10, background: T.teal50, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Icon name={c.icon} size={19} color={T.teal700} />
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 700, fontSize: 14, color: T.ink900 }}>{c.label}</div>
                      <div style={{ fontSize: 12.5, color: T.ink500 }}>{c.desc}</div>
                    </div>
                    <Icon name="chevronRight" size={16} color={T.ink300} />
                  </button>
                ))}
              </div>
            </>
          )}

          {mode === 'signup' && step === 1.5 && (
            <>
              <button onClick={() => setStep(1)} style={{ background: 'none', border: 'none', color: T.ink500, fontSize: 12.5, fontWeight: 600, cursor: 'pointer', marginBottom: 14, padding: 0 }}>
                ← back
              </button>
              <div style={{ fontSize: 13, fontWeight: 600, color: T.ink700, marginBottom: 12 }}>Which team are you on?</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {staffCards.map(c => (
                  <button key={c.key} onClick={() => { setStaffType(c.key); setStep(2); }} style={{
                    display: 'flex', flexDirection: 'column', gap: 8, padding: '14px', borderRadius: 12,
                    border: `1px solid ${T.ink100}`, background: T.white, cursor: 'pointer', textAlign: 'left',
                  }}>
                    <Icon name={c.icon} size={19} color={T.teal700} />
                    <div style={{ fontWeight: 700, fontSize: 13, color: T.ink900 }}>{c.label}</div>
                    <div style={{ fontSize: 11.5, color: T.ink500, lineHeight: 1.4 }}>{c.desc}</div>
                  </button>
                ))}
              </div>
            </>
          )}

          {mode === 'signup' && step === 2 && (
            <>
              <button onClick={() => setStep(role === 'staff' ? 1.5 : 1)} style={{ background: 'none', border: 'none', color: T.ink500, fontSize: 12.5, fontWeight: 600, cursor: 'pointer', marginBottom: 14, padding: 0 }}>
                ← back
              </button>
              <Field label="Full name">
                <input style={inputStyle} placeholder="Jane Doe" value={form.name} onChange={e => set('name', e.target.value)} />
              </Field>
              <Field label="Email">
                <input style={inputStyle} type="email" placeholder="you@example.com" value={form.email} onChange={e => set('email', e.target.value)} />
              </Field>
              <Field label="Password">
                <input style={inputStyle} type="password" placeholder="••••••••" value={form.password} onChange={e => set('password', e.target.value)} />
              </Field>

              {staffType === 'doctor' && (
                <>
                  <Field label="Department / specialty">
                    <input style={inputStyle} placeholder="e.g. Cardiology" value={form.dept} onChange={e => set('dept', e.target.value)} />
                  </Field>
                  <div style={{ display: 'flex', gap: 12 }}>
                    <div style={{ flex: 1 }}>
                      <Field label="Room">
                        <input style={inputStyle} placeholder="304" value={form.room} onChange={e => set('room', e.target.value)} />
                      </Field>
                    </div>
                    <div style={{ flex: 1 }}>
                      <Field label="Hospital">
                        <input style={inputStyle} placeholder="Max Saket" value={form.hospital} onChange={e => set('hospital', e.target.value)} />
                      </Field>
                    </div>
                  </div>
                  <Field label="Available timings">
                    <input style={inputStyle} placeholder="Mon-Fri 10:00-13:00" value={form.timings} onChange={e => set('timings', e.target.value)} />
                  </Field>
                </>
              )}
              {(staffType === 'tpa' || staffType === 'lab' || staffType === 'admin') && (
                <Field label="Hospital / organization">
                  <input style={inputStyle} placeholder="Max Saket" value={form.hospital} onChange={e => set('hospital', e.target.value)} />
                </Field>
              )}

              <Button style={{ width: '100%', justifyContent: 'center', marginTop: 8 }} onClick={finishSignup}>
                Create account
              </Button>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

/* ============================================================
   PATIENT — Dashboard / Upload / Ask / Appointments / Queue
   ============================================================ */
function PatientApp({ user, onLogout }) {
  const [page, setPage] = useState('dashboard');
  const docs = MOCK.documents[user.id] || [];
  const myDocs = docs.filter(d => d.uploaded_by === user.id);
  const careTeamDocs = docs.filter(d => d.uploaded_by !== user.id);
  const myAppts = MOCK.appointments.filter(a => a.patientId === user.id);

  const nav = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'upload', label: 'Upload documents', icon: 'upload' },
    { key: 'ask', label: 'Ask HeyDoc', icon: 'chat' },
    { key: 'appointments', label: 'Appointments', icon: 'calendar' },
    { key: 'queue', label: 'My queue', icon: 'clock' },
  ];

  return (
    <Shell role="patient" userName={user.name} nav={nav} active={page} onNav={setPage} onLogout={onLogout}>
      {page === 'dashboard' && <PatientDashboard docs={docs} appts={myAppts} onNav={setPage} />}
      {page === 'upload' && <PatientUpload myDocs={myDocs} careTeamDocs={careTeamDocs} />}
      {page === 'ask' && <AskHeyDoc patientId={user.id} />}
      {page === 'appointments' && <PatientAppointments appts={myAppts} />}
      {page === 'queue' && <PatientQueue appts={myAppts} />}
    </Shell>
  );
}

function StatCard({ icon, label, value, sub, color }) {
  return (
    <Card style={{ flex: 1 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <div style={{ width: 32, height: 32, borderRadius: 9, background: `${color}18`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Icon name={icon} size={16} color={color} />
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, color: T.ink500 }}>{label}</div>
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: T.ink900 }}>{value}</div>
      {sub && <div style={{ fontSize: 12.5, color: T.ink500, marginTop: 2 }}>{sub}</div>}
    </Card>
  );
}

function PatientDashboard({ docs, appts, onNav }) {
  const meds = docs.filter(d => d.semantic_type === 'medication_history').length;
  const next = appts[0];
  return (
    <>
      <PageHeader title="Welcome back" sub="Your personal health memory assistant." />
      <div style={{ display: 'flex', gap: 16, marginBottom: 20 }}>
        <StatCard icon="file" label="Documents" value={docs.length} sub="medical records stored" color={T.teal600} />
        <StatCard icon="user" label="Medication chunks" value={meds} sub="from your records" color={T.blue600} />
        <StatCard icon="calendar" label="Appointments" value={appts.length} sub="upcoming & past" color={T.coral600} />
      </div>
      <div style={{ display: 'flex', gap: 16 }}>
        <Card style={{ flex: 1.3 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <Icon name="chat" size={18} color={T.teal600} />
            <div style={{ fontWeight: 700, fontSize: 15 }}>Ask HeyDoc</div>
          </div>
          <p style={{ fontSize: 13.5, color: T.ink500, lineHeight: 1.6, margin: '0 0 14px' }}>
            Ask natural-language questions about your health history. Answers are grounded in your uploaded records, with sources cited.
          </p>
          <Button onClick={() => onNav('ask')}>Start conversation <Icon name="arrowRight" size={14} color="#fff" /></Button>
        </Card>
        <Card style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 12 }}>Next appointment</div>
          {next ? (
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: T.ink900 }}>{fmtTime(next.time)} today</div>
              <div style={{ fontSize: 13, color: T.ink500, marginTop: 2 }}>
                {MOCK.doctors.find(d => d.id === next.doctorId)?.name}
              </div>
              <Badge bg={T.teal50} fg={T.teal700}>{next.type === 'admission' ? 'Admission' : next.type === 'new' ? 'New patient' : 'Follow-up'}</Badge>
            </div>
          ) : <EmptyState icon="calendar" title="No upcoming appointments" />}
        </Card>
      </div>
    </>
  );
}

function DocRow({ doc }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0', borderBottom: `1px solid ${T.ink100}` }}>
      <Icon name="file" size={17} color={T.ink500} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: T.ink900, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.name}</div>
        <div style={{ fontSize: 12, color: T.ink500 }}>{doc.date}</div>
      </div>
      <SemanticTag type={doc.semantic_type} />
    </div>
  );
}

function PatientUpload({ myDocs, careTeamDocs }) {
  const [dropped, setDropped] = useState(false);
  return (
    <>
      <PageHeader title="Upload documents" sub="HeyDoc will OCR, classify, and chunk your records automatically." />
      <Card style={{ marginBottom: 24, textAlign: 'center', padding: '40px 20px', border: `2px dashed ${T.ink100}` }}
        onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); setDropped(true); }}>
        <Icon name="upload" size={26} color={T.teal600} />
        <div style={{ fontWeight: 700, fontSize: 15, color: T.ink900, marginTop: 12 }}>Drag & drop medical documents here</div>
        <div style={{ fontSize: 12.5, color: T.ink500, marginTop: 4 }}>Supports PDF, PNG, JPG up to 10MB</div>
        <Button variant="secondary" style={{ marginTop: 14 }} onClick={() => setDropped(true)}>Select files</Button>
        {dropped && (
          <div style={{ marginTop: 16, fontSize: 12.5, color: T.teal700, background: T.teal50, padding: '8px 14px', borderRadius: 8, display: 'inline-block' }}>
            Wire this to ingestion.ingest_document(patient_id, file, models)
          </div>
        )}
      </Card>

      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 4 }}>Your uploads</div>
      <Card style={{ marginBottom: 24 }}>
        {myDocs.length ? myDocs.map(d => <DocRow key={d.id} doc={d} />) : <EmptyState icon="file" title="No documents uploaded yet" />}
      </Card>

      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 4 }}>Documents from your care team</div>
      <p style={{ fontSize: 12.5, color: T.ink500, margin: '0 0 10px' }}>Scans, reports, and results uploaded by your doctor, lab, or insurance desk.</p>
      <Card>
        {careTeamDocs.length ? careTeamDocs.map(d => <DocRow key={d.id} doc={d} />) : <EmptyState icon="file" title="Nothing here yet" />}
      </Card>
    </>
  );
}

function AskHeyDoc({ patientId }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const suggestions = ['What medications am I currently on?', 'Summarize my recent lab reports', 'What was I prescribed after my surgery?', 'When was my last follow-up?'];

  function send(text) {
    if (!text.trim()) return;
    const userMsg = { role: 'user', text };
    setMessages(m => [...m, userMsg]);
    setInput('');
    setTimeout(() => {
      setMessages(m => [...m, {
        role: 'assistant',
        text: `[Mock response — wire to retrieval.rag_query("${patientId}", "${text}", models)]`,
        sources: [{ name: 'Discharge_Summary_16May.pdf', type: 'discharge_summary' }, { name: 'Prescription_Ceroxim.pdf', type: 'prescription' }],
      }]);
    }, 500);
  }

  return (
    <>
      <PageHeader title="Ask HeyDoc" sub="Answers are grounded in your uploaded records, with sources cited." />
      <Card style={{ minHeight: 380, display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1 }}>
          {messages.length === 0 ? (
            <div style={{ padding: '20px 0' }}>
              <EmptyState icon="chat" title="How can I help you today?" sub="Ask about medications, diagnoses, lab results, or anything from your records." />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 16 }}>
                {suggestions.map(s => (
                  <button key={s} onClick={() => send(s)} style={{ textAlign: 'left', fontSize: 12.5, padding: '10px 12px', borderRadius: 9, border: `1px solid ${T.ink100}`, background: T.cream, cursor: 'pointer', color: T.ink700 }}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {messages.map((m, i) => (
                <div key={i} style={{ alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '78%' }}>
                  <div style={{
                    background: m.role === 'user' ? T.teal600 : T.cream, color: m.role === 'user' ? '#fff' : T.ink900,
                    padding: '10px 14px', borderRadius: 12, fontSize: 13.5, lineHeight: 1.5,
                  }}>
                    {m.text}
                  </div>
                  {m.sources && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                      {m.sources.map((s, j) => (
                        <Badge key={j} bg={T.ink100} fg={T.ink700}><Icon name="file" size={11} /> {s.name}</Badge>
                      ))}
                    </div>
                  )}
                  {m.role === 'assistant' && <AiNotice />}
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 16, borderTop: `1px solid ${T.ink100}`, paddingTop: 16 }}>
          <input style={inputStyle} placeholder="Ask about your medical history..." value={input}
            onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && send(input)} />
          <Button onClick={() => send(input)}><Icon name="arrowRight" size={15} color="#fff" /></Button>
        </div>
      </Card>
    </>
  );
}

function PatientAppointments({ appts }) {
  const [booking, setBooking] = useState(false);
  return (
    <>
      <PageHeader title="Appointments" sub="Schedule visits and complete pre-admission formalities before you arrive." />
      <Button style={{ marginBottom: 20 }} onClick={() => setBooking(b => !b)}><Icon name="plus" size={15} color="#fff" /> Book appointment</Button>

      {booking && (
        <Card style={{ marginBottom: 20 }}>
          <Field label="Doctor">
            <select style={inputStyle}>
              {MOCK.doctors.map(d => <option key={d.id}>{d.name} — {d.dept}</option>)}
            </select>
          </Field>
          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1 }}><Field label="Date"><input style={inputStyle} type="date" /></Field></div>
            <div style={{ flex: 1 }}><Field label="Time"><input style={inputStyle} type="time" /></Field></div>
          </div>
          <Field label="Visit type">
            <select style={inputStyle}><option>OPD consultation</option><option>Hospital admission</option></select>
          </Field>
          <Button onClick={() => setBooking(false)}>Confirm booking</Button>
        </Card>
      )}

      {appts.map(a => {
        const doc = MOCK.doctors.find(d => d.id === a.doctorId);
        const isAdmission = a.type === 'admission';
        return (
          <Card key={a.id} style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{doc?.name}</div>
                <div style={{ fontSize: 13, color: T.ink500 }}>{doc?.dept} · Room {doc?.room} · {fmtTime(a.time)} today</div>
              </div>
              <Badge bg={isAdmission ? T.coral100 : T.teal100} fg={isAdmission ? T.coral600 : T.teal700}>
                {isAdmission ? 'Admission' : a.type === 'new' ? 'New patient' : 'Follow-up'}
              </Badge>
            </div>
            {isAdmission && (
              <div style={{ marginTop: 16, borderTop: `1px solid ${T.ink100}`, paddingTop: 14 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: T.ink700, marginBottom: 10 }}>Pre-admission formalities</div>
                {[
                  { label: 'Insurance verification', done: true },
                  { label: 'Documentation review', done: true },
                  { label: 'Payment', done: false },
                ].map(s => (
                  <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', fontSize: 13 }}>
                    <div style={{ width: 18, height: 18, borderRadius: '50%', background: s.done ? T.teal600 : T.ink100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {s.done && <Icon name="check" size={11} color="#fff" />}
                    </div>
                    <span style={{ color: s.done ? T.ink900 : T.ink500 }}>{s.label}</span>
                  </div>
                ))}
                <p style={{ fontSize: 12, color: T.ink500, marginTop: 10 }}>Complete these before arrival so you skip the front-desk queue.</p>
              </div>
            )}
          </Card>
        );
      })}
    </>
  );
}

function PatientQueue({ appts }) {
  const next = appts[0];
  if (!next) return (<><PageHeader title="My queue" sub="Check in and track your live position." /><Card><EmptyState icon="calendar" title="No upcoming appointments" sub="Book an appointment to use digital check-in." /></Card></>);
  const mins = minsUntil(next.time);
  const checkInOpen = mins <= 30;
  const qEntry = MOCK.queue.find(q => q.appointmentId === next.id);
  return (
    <>
      <PageHeader title="My queue" sub="Check in and track your live position in real time." />
      <Card>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 4 }}>{MOCK.doctors.find(d => d.id === next.doctorId)?.name}</div>
        <div style={{ fontSize: 13, color: T.ink500, marginBottom: 18 }}>{fmtTime(next.time)} today</div>

        {!checkInOpen ? (
          <div style={{ background: T.cream, borderRadius: 10, padding: 16, textAlign: 'center' }}>
            <Icon name="clock" size={20} color={T.ink500} />
            <div style={{ fontWeight: 600, fontSize: 13.5, marginTop: 8 }}>Check-in opens 30 minutes before your appointment</div>
            <div style={{ fontSize: 12.5, color: T.ink500, marginTop: 2 }}>Opens in {mins - 30} min</div>
          </div>
        ) : qEntry?.checkedIn ? (
          <div style={{ background: T.teal50, borderRadius: 10, padding: 18, textAlign: 'center' }}>
            <div style={{ fontSize: 13, color: T.teal700, fontWeight: 600 }}>You're checked in</div>
            <div style={{ fontSize: 34, fontWeight: 700, color: T.teal700, margin: '6px 0' }}>#{qEntry.position}</div>
            <div style={{ fontSize: 12.5, color: T.ink500 }}>in line · est. wait ~{qEntry.position * 8} min</div>
          </div>
        ) : (
          <Button style={{ width: '100%', justifyContent: 'center' }}>Check in now</Button>
        )}
      </Card>
    </>
  );
}

/* ============================================================
   DOCTOR
   ============================================================ */
function VaultView({ patientId, emphasize }) {
  const docs = MOCK.documents[patientId] || [];
  const order = emphasize ? ['diagnosis', 'medication_history', 'lab_reports', 'surgical_history', 'follow_up_notes', 'patient_information'] : Object.keys(SEMANTIC);
  const grouped = order.map(t => ({ type: t, docs: docs.filter(d => d.semantic_type === t) })).filter(g => g.docs.length);
  if (!docs.length) return <EmptyState icon="file" title="No records for this patient yet" />;
  return (
    <div>
      {grouped.map(g => (
        <div key={g.type} style={{ marginBottom: 18 }}>
          <div style={{ marginBottom: 8 }}><SemanticTag type={g.type} /></div>
          {g.docs.map(d => <DocRow key={d.id} doc={d} />)}
        </div>
      ))}
    </div>
  );
}

function UploadForPatient({ role }) {
  const [patientId, setPatientId] = useState(MOCK.patients[0].id);
  const [done, setDone] = useState(false);
  const fnName = role === 'lab' ? 'imaging.ingest_scan(...)  or  ingestion.ingest_document(...)' : 'ingestion.ingest_document(patient_id, file, models)';
  return (
    <Card>
      <Field label="Patient">
        <select style={inputStyle} value={patientId} onChange={e => { setPatientId(e.target.value); setDone(false); }}>
          {MOCK.patients.map(p => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}
        </select>
      </Field>
      <div style={{ border: `2px dashed ${T.ink100}`, borderRadius: 12, padding: '28px 16px', textAlign: 'center', marginTop: 6 }}>
        <Icon name="upload" size={22} color={T.teal600} />
        <div style={{ fontSize: 13, fontWeight: 600, marginTop: 8 }}>Upload on behalf of this patient</div>
        <Button variant="secondary" style={{ marginTop: 12 }} onClick={() => setDone(true)}>Select file</Button>
      </div>
      {done && (
        <div style={{ marginTop: 14, fontSize: 12.5, color: T.teal700, background: T.teal50, padding: '10px 14px', borderRadius: 8 }}>
          Tagged uploaded_by = current staff id → calls <code style={{ fontSize: 11.5 }}>{fnName}</code>, appears in patient's "care team" section.
        </div>
      )}
    </Card>
  );
}

function DoctorApp({ user, onLogout }) {
  const [page, setPage] = useState('dashboard');
  const [selectedPatient, setSelectedPatient] = useState(null);
  const myAppts = MOCK.appointments.filter(a => a.doctorId === user.id || true);
  const doc = MOCK.doctors[0];

  const nav = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'schedule', label: 'My schedule', icon: 'calendar' },
    { key: 'queue', label: 'Patient queue', icon: 'clock' },
    { key: 'lookup', label: 'Patient lookup', icon: 'search' },
    { key: 'upload', label: 'Upload for patient', icon: 'upload' },
  ];

  return (
    <Shell role="doctor" userName={user.name} nav={nav} active={page} onNav={setPage} onLogout={onLogout}>
      {page === 'dashboard' && (
        <>
          <PageHeader title={`Good afternoon, ${user.name}`} sub={`${doc.dept} · Room ${doc.room} · ${doc.hospital}`} />
          <div style={{ display: 'flex', gap: 16, marginBottom: 20 }}>
            <StatCard icon="clock" label="In queue today" value={MOCK.queue.length} color={T.blue600} />
            <StatCard icon="calendar" label="Appointments" value={myAppts.length} color={T.teal600} />
            <StatCard icon="user" label="New patients" value={myAppts.filter(a => a.type === 'new').length} color={T.coral600} />
          </div>
          <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 10 }}>Up next</div>
          {myAppts.slice(0, 3).map(a => {
            const p = MOCK.patients.find(pt => pt.id === a.patientId);
            return (
              <Card key={a.id} style={{ marginBottom: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{p?.name}</div>
                  <div style={{ fontSize: 12.5, color: T.ink500 }}>{fmtTime(a.time)} · {a.type === 'new' ? 'New patient' : 'Follow-up'}</div>
                </div>
                <Button variant="secondary" onClick={() => { setSelectedPatient(p.id); setPage('lookup'); }}>View vault</Button>
              </Card>
            );
          })}
        </>
      )}

      {page === 'schedule' && (
        <>
          <PageHeader title="My schedule" sub="Edit your availability — patients book against these slots." />
          <Card>
            <Field label="Department"><input style={inputStyle} defaultValue={doc.dept} /></Field>
            <div style={{ display: 'flex', gap: 12 }}>
              <div style={{ flex: 1 }}><Field label="Room"><input style={inputStyle} defaultValue={doc.room} /></Field></div>
              <div style={{ flex: 1 }}><Field label="Hospital"><input style={inputStyle} defaultValue={doc.hospital} /></Field></div>
            </div>
            <Field label="Available timings"><input style={inputStyle} defaultValue={doc.timings} /></Field>
            <Button>Save changes</Button>
          </Card>
        </>
      )}

      {page === 'queue' && (
        <>
          <PageHeader title="Patient queue" sub="Manually notify the next patient when you're ready." />
          {MOCK.queue.map(q => {
            const appt = MOCK.appointments.find(a => a.id === q.appointmentId);
            const p = MOCK.patients.find(pt => pt.id === appt.patientId);
            return (
              <Card key={q.appointmentId} style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{ width: 30, height: 30, borderRadius: '50%', background: T.blue50, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 13, color: T.blue600 }}>{q.position}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{p.name}</div>
                  <div style={{ fontSize: 12.5, color: T.ink500 }}>{fmtTime(appt.time)} · {appt.type === 'new' ? 'New patient' : 'Follow-up'}</div>
                </div>
                <Badge bg={q.checkedIn ? T.teal100 : T.ink100} fg={q.checkedIn ? T.teal700 : T.ink500}>{q.checkedIn ? 'Checked in' : 'Not arrived'}</Badge>
                <Button variant="secondary" disabled={!q.checkedIn}><Icon name="bell" size={13} color={T.teal700} /> Notify</Button>
              </Card>
            );
          })}
        </>
      )}

      {page === 'lookup' && (
        <>
          <PageHeader title="Patient lookup" sub="Search a patient to view their full vault." />
          <Field label="Patient">
            <select style={inputStyle} value={selectedPatient || ''} onChange={e => setSelectedPatient(e.target.value)}>
              <option value="">Select a patient...</option>
              {MOCK.patients.map(p => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}
            </select>
          </Field>
          {selectedPatient && <VaultView patientId={selectedPatient} emphasize />}
        </>
      )}

      {page === 'upload' && (<><PageHeader title="Upload for patient" sub="Add a scan, report, or note directly to a patient's vault." /><UploadForPatient role="doctor" /></>)}
    </Shell>
  );
}

/* ============================================================
   TPA / Insurance desk
   ============================================================ */
function TpaApp({ user, onLogout }) {
  const [page, setPage] = useState('dashboard');
  const nav = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'lookup', label: 'Patient lookup', icon: 'search' },
    { key: 'upload', label: 'Upload for patient', icon: 'upload' },
    { key: 'claims', label: 'Claims tracker', icon: 'shield' },
  ];
  const [selectedPatient, setSelectedPatient] = useState(null);
  const claimPatients = Object.keys(MOCK.deptStatus);

  return (
    <Shell role="tpa" userName={user.name} nav={nav} active={page} onNav={setPage} onLogout={onLogout}>
      {page === 'dashboard' && (
        <>
          <PageHeader title="Insurance desk" sub="Coordinate cashless claims and pre-authorization." />
          <div style={{ display: 'flex', gap: 16 }}>
            <StatCard icon="shield" label="Pending pre-auth" value={claimPatients.filter(p => MOCK.deptStatus[p].insurance === 'pending').length} color={T.amber600} />
            <StatCard icon="check" label="Approved" value={claimPatients.filter(p => MOCK.deptStatus[p].insurance === 'approved').length} color={T.teal600} />
          </div>
        </>
      )}
      {page === 'lookup' && (
        <>
          <PageHeader title="Patient lookup" />
          <Field label="Patient">
            <select style={inputStyle} value={selectedPatient || ''} onChange={e => setSelectedPatient(e.target.value)}>
              <option value="">Select a patient...</option>
              {MOCK.patients.map(p => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}
            </select>
          </Field>
          {selectedPatient && <VaultView patientId={selectedPatient} />}
        </>
      )}
      {page === 'upload' && (<><PageHeader title="Upload for patient" sub="Insurance documents, pre-auth letters, claim paperwork." /><UploadForPatient role="tpa" /></>)}
      {page === 'claims' && (
        <>
          <PageHeader title="Claims tracker" />
          {claimPatients.map(pid => {
            const p = MOCK.patients.find(pt => pt.id === pid);
            const s = MOCK.deptStatus[pid].insurance;
            return (
              <Card key={pid} style={{ marginBottom: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{p?.name}</div>
                <Badge bg={s === 'approved' ? T.teal100 : T.amber100} fg={s === 'approved' ? T.teal700 : T.amber600}>{s}</Badge>
              </Card>
            );
          })}
        </>
      )}
    </Shell>
  );
}

/* ============================================================
   Lab / diagnostics
   ============================================================ */
function LabApp({ user, onLogout }) {
  const [page, setPage] = useState('dashboard');
  const [selectedPatient, setSelectedPatient] = useState(null);
  const nav = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'lookup', label: 'Patient lookup', icon: 'search' },
    { key: 'upload', label: 'Upload results', icon: 'upload' },
    { key: 'pending', label: 'Pending work', icon: 'clock' },
  ];
  const pending = Object.entries(MOCK.deptStatus).filter(([, s]) => s.labs === 'pending');

  return (
    <Shell role="lab" userName={user.name} nav={nav} active={page} onNav={setPage} onLogout={onLogout}>
      {page === 'dashboard' && (
        <>
          <PageHeader title="Lab / diagnostics" sub="Upload test results and scans for processing." />
          <StatCard icon="flask" label="Pending orders" value={pending.length} color="#6a3fa0" />
        </>
      )}
      {page === 'lookup' && (
        <>
          <PageHeader title="Patient lookup" />
          <Field label="Patient">
            <select style={inputStyle} value={selectedPatient || ''} onChange={e => setSelectedPatient(e.target.value)}>
              <option value="">Select a patient...</option>
              {MOCK.patients.map(p => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}
            </select>
          </Field>
          {selectedPatient && <VaultView patientId={selectedPatient} />}
        </>
      )}
      {page === 'upload' && (<><PageHeader title="Upload test results" sub="Reports go through ingestion. Scan images go through imaging.ingest_scan with Gemini Vision + BioViL-T flagging." /><UploadForPatient role="lab" /></>)}
      {page === 'pending' && (
        <>
          <PageHeader title="Pending work" />
          {pending.map(([pid]) => {
            const p = MOCK.patients.find(pt => pt.id === pid);
            return <Card key={pid} style={{ marginBottom: 10 }}><div style={{ fontWeight: 600, fontSize: 14 }}>{p?.name}</div><div style={{ fontSize: 12.5, color: T.ink500 }}>Awaiting upload</div></Card>;
          })}
          {!pending.length && <EmptyState icon="check" title="Nothing pending" />}
        </>
      )}
    </Shell>
  );
}

/* ============================================================
   Hospital admin
   ============================================================ */
function AdminApp({ user, onLogout }) {
  const [page, setPage] = useState('dashboard');
  const [selected, setSelected] = useState(null);
  const nav = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid' },
    { key: 'intake', label: 'Intake forms', icon: 'file' },
    { key: 'admissions', label: "Today's arrivals", icon: 'calendar' },
  ];
  const admissions = MOCK.appointments.filter(a => a.type === 'admission' || a.type === 'new');

  return (
    <Shell role="admin" userName={user.name} nav={nav} active={page} onNav={setPage} onLogout={onLogout}>
      {page === 'dashboard' && (
        <>
          <PageHeader title="Front desk" sub="Hospital intake automation — generate, verify, confirm." />
          <div style={{ display: 'flex', gap: 16, marginBottom: 20 }}>
            <StatCard icon="calendar" label="Today's arrivals" value={admissions.length} color={T.coral600} />
            <StatCard icon="clock" label="Pending verification" value={admissions.filter(a => a.intakeStatus === 'pending').length} color={T.amber600} />
          </div>
        </>
      )}

      {page === 'admissions' && (
        <>
          <PageHeader title="Today's arrivals" />
          {admissions.map(a => {
            const p = MOCK.patients.find(pt => pt.id === a.patientId);
            return (
              <Card key={a.id} style={{ marginBottom: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{p?.name}</div>
                  <div style={{ fontSize: 12.5, color: T.ink500 }}>{fmtTime(a.time)} · {a.type}</div>
                </div>
                <Button variant="secondary" onClick={() => { setSelected(a); setPage('intake'); }}>Open intake form</Button>
              </Card>
            );
          })}
        </>
      )}

      {page === 'intake' && (
        <>
          <PageHeader title="Intake form" sub="Pre-filled from the patient's vault. Review every field before confirming." />
          {!selected ? (
            <Field label="Select arrival">
              <select style={inputStyle} onChange={e => setSelected(admissions.find(a => a.id === e.target.value))}>
                <option value="">Choose a patient...</option>
                {admissions.map(a => <option key={a.id} value={a.id}>{MOCK.patients.find(p => p.id === a.patientId)?.name}</option>)}
              </select>
            </Field>
          ) : (
            <IntakeForm appt={selected} />
          )}
        </>
      )}
    </Shell>
  );
}

function IntakeForm({ appt }) {
  const p = MOCK.patients.find(pt => pt.id === appt.patientId);
  const status = MOCK.deptStatus[appt.patientId] || { insurance: 'pending', labs: 'pending', documentation: 'pending' };
  const [verified, setVerified] = useState(false);

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 14 }}>Cross-department status</div>
        <div style={{ display: 'flex', gap: 10 }}>
          {Object.entries(status).map(([dept, s]) => (
            <div key={dept} style={{ flex: 1, textAlign: 'center', padding: '10px 6px', borderRadius: 10, background: T.cream }}>
              <div style={{ fontSize: 11.5, color: T.ink500, textTransform: 'capitalize' }}>{dept}</div>
              <Badge bg={s === 'approved' || s === 'verified' ? T.teal100 : T.amber100} fg={s === 'approved' || s === 'verified' ? T.teal700 : T.amber600}>{s}</Badge>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 14 }}>Admission summary — {p?.name}</div>
        <Field label="Allergies (from vault)"><input style={inputStyle} defaultValue="Penicillin — noted in 2024 discharge summary" /></Field>
        <Field label="Current medications (from vault)"><input style={inputStyle} defaultValue="Ceroxim-XP 625mg, Pantop 40mg" /></Field>
        <Field label="Insurance details"><input style={inputStyle} defaultValue="Star Health — Policy #SH2024118832" /></Field>
        <Field label="Past diagnoses"><input style={inputStyle} defaultValue="Recurrent dermoid cyst, nasal tip" /></Field>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 18, padding: '12px 14px', background: T.coral50, borderRadius: 10 }}>
          <input type="checkbox" checked={verified} onChange={e => setVerified(e.target.checked)} style={{ width: 16, height: 16 }} />
          <span style={{ fontSize: 13, color: T.coral600, fontWeight: 600 }}>I have reviewed every field above against the source documents</span>
        </div>
        <Button style={{ marginTop: 14 }} disabled={!verified}>Verify and confirm admission</Button>
        <p style={{ fontSize: 11.5, color: T.ink500, marginTop: 8 }}>Nothing is finalized automatically — this requires explicit human confirmation.</p>
      </Card>
    </>
  );
}

/* ============================================================
   ROOT
   ============================================================ */
export default function HeyDoc() {
  const [user, setUser] = useState(null);

  if (!user) return <AuthScreen onSignedIn={setUser} />;

  const apps = { patient: PatientApp, doctor: DoctorApp, tpa: TpaApp, lab: LabApp, admin: AdminApp };
  const App = apps[user.role] || PatientApp;
  return <App user={user} onLogout={() => setUser(null)} />;
}
