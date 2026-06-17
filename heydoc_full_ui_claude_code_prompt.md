# HeyDoc — Full Multi-Role UI Build Prompt for Claude Code

## Context — read this first

This is "TheArch" for a hackathon (IIT Kharagpur, RAG + Agentic AI track).
Product name: **HeyDoc**. The RAG/ingestion backend already exists and is
**working** — three Python modules:

- `ingestion.py` — OCR (PyMuPDF → docTR → Gemini Vision hybrid escalation),
  document classification, field extraction, semantic chunking (6 categories:
  `patient_information`, `diagnosis`, `medication_history`, `lab_reports`,
  `surgical_history`, `follow_up_notes`), embedding (BAAI/bge-large-en-v1.5),
  ChromaDB storage. Public API: `init(gemini_api_key) -> models dict`,
  `ingest_document(patient_id, file_path, models) -> dict`,
  `vector_search(patient_id, query, models, top_k, doc_type_filter,
  semantic_type_filter) -> list[dict]`, `build_bm25(patient_id, models)`,
  `inspect_all_chunks(patient_id, models)`.
- `retrieval.py` — Phase 2/3 RAG query layer, **already built**: query
  normalisation (OCR-typo fixing, medical abbreviation expansion, fuzzy
  correction), hybrid search (vector + BM25 → Reciprocal Rank Fusion),
  cross-encoder reranking (BAAI/bge-reranker-v2-m3), Gemini 2.5 Flash answer
  generation with retry/backoff. Public API:
  `init_reranker(models)` (call once after `ingestion.init()`),
  `rag_query(patient_id, question, models, top_k, semantic_type_filter,
  doc_type_filter) -> dict` returning
  `{"answer": str, "sources": list[dict], "context": str, "chunk_count": int,
  "norm_query": str}`.
- `imaging.py` — handles raw scan **images** (not reports — actual pixel
  data: X-ray, CT, MRI, ultrasound). Detects modality from filename, uses
  Gemini 2.5 Flash Vision for a structured clinical description, and for
  chest X-rays specifically runs BioViL-T zero-shot phrase scoring for
  abnormality flags. Stores as `doc_type=imaging_scan` in the same ChromaDB.
  Public API: `load_imaging_models() -> dict`,
  `ingest_scan(patient_id, path, models, imaging_models) -> dict`.

**Do not modify any of these three files.** If something about their API is
inconvenient, tell me — don't change them yourself. Your job in this task is
purely the UI/app layer that calls into them.

ChromaDB is used **only** for document chunks/embeddings (the RAG knowledge
base), scoped per `patient_id` via metadata filtering with `$and` for
multi-field filters. It is **not** an account/auth/appointments database —
you need a separate lightweight store for that (see Data Model section).

## What exists already (reference, don't rebuild from scratch)

A rough prototype UI already exists for the **patient** role with four pages:
Dashboard, Upload Documents, Ask HeyDoc, My Queue. Sidebar nav, teal/white
color scheme, card-based dashboard. Screenshots are attached/described
separately — treat this as the visual starting point and design language to
extend, not as a finished spec. It currently has no auth, no real backend
wiring, and no appointment/admission/faculty features. You're building all
of that now, plus three entirely new role-based experiences.

## The core thing to build: sign-in + 4 distinct role experiences

### Sign-in flow

- Email/password sign-in (no need for Google OAuth — keep this simple and
  fast to build, this is a hackathon demo).
- After first sign-in, the user picks a role: **Patient** or **Hospital
  Staff**. If Hospital Staff, they then specify which kind:
  - **Doctor**
  - **TPA / Corporate / Insurance Desk** (handles cashless claims,
    pre-authorization coordination with insurers, corporate empanelment)
  - **Lab / Diagnostics** (lab technicians/physicians who upload test
    results — this is the role for what the user was trying to name; in
    Indian hospital terminology this is typically called "Lab" or
    "Diagnostics" staff, sometimes "Pathology desk")
  - **Hospital Admin / Front Desk** (handles intake, admission paperwork,
    coordinates with other departments)
- Every signed-up user gets a unique ID matching the existing `patient_id`
  convention used throughout the RAG pipeline (e.g. `patient_001`,
  `doctor_001`, `staff_tpa_001` — keep IDs simple and consistent in format
  since `patient_id` is the literal key every backend function expects).
- Role-specific onboarding fields to collect at signup:
  - **Doctor**: full name, department/specialty, hospital affiliation,
    consultation room number, available days/timings (structured schedule,
    not free text), position/title.
  - **TPA/Insurance**: name, organization, which insurers/TPAs they handle,
    hospital affiliation.
  - **Lab/Diagnostics**: name, lab department, hospital affiliation.
  - **Hospital Admin**: name, department, hospital affiliation.
  - **Patient**: name, date of birth, contact info — keep this minimal,
    this is a hackathon demo not a real onboarding flow.

## Patient experience (extend the existing 4-page prototype)

Keep Dashboard, Upload Documents, Ask HeyDoc, My Queue, and add:

### Upload Documents — add a sub-section
Alongside patient-uploaded documents, show a clearly separated section:
**"Documents from your care team"** — files uploaded by doctors, labs, or TPA
staff on this patient's behalf (scans, test results, insurance paperwork).
Same visual list style, different source label so the patient can tell what
they uploaded themselves vs what their hospital uploaded for them. Both feed
the same ingestion pipeline and end up in the same patient vault — the
distinction is purely about *who* uploaded it, tracked as an `uploaded_by`
field alongside `patient_id`.

### Ask HeyDoc — wire to the real backend
This page already has the right shape (suggested questions, chat input).
Wire it to `retrieval.rag_query(patient_id, question, models)`. Display:
the answer, the cited source documents (`sources` from the response — each
has `meta` with `file_name`, `doc_type`, `semantic_type`), and visibly
indicate this is AI-assisted information with a path to contact a real
doctor (non-negotiable — never present this as a diagnosis).

### Appointments (new — currently just a stub link on the dashboard)
Build out a real appointment scheduling flow:
- Browse/search doctors by department or name, see their available slots
  (based on the schedule the doctor set at signup).
- Book an appointment for a specific date/time with a specific doctor.
- See upcoming and past appointments.
- **Pre-admission / pre-visit formalities**: this is the actual core
  pitch of the hackathon project — let the patient complete intake
  paperwork, insurance verification, and payment *before* arriving, so they
  aren't stuck waiting an hour at the hospital desk like the real personal
  experience that inspired this project. This should be its own clear step
  in the appointment flow when the appointment type is a hospital admission
  (vs a simple OPD consultation) — show what still needs verification vs
  what's been completed, and let the patient see status update as hospital
  staff process it on their end.

### My Queue — make it real
- Currently shows "no upcoming appointments" because there's no appointment
  data yet — once Appointments exists, this page should show the patient's
  upcoming appointment and, critically: **queue/check-in only activates
  starting 30 minutes before the scheduled appointment time.** Before that
  window, show the appointment details with a countdown or "check-in opens
  at [time]" message. Once inside the window, allow check-in and show live
  queue position + estimated wait time.

## Doctor experience (new)

- **My Schedule**: view/edit their availability (days, time blocks, room),
  matches what they set at signup but editable going forward.
- **My Queue / Patient List**: today's appointments in order, each showing
  patient name/ID, appointment time, whether it's a new patient or follow-up
  (pull this from whether the patient has prior documents in their vault via
  `vector_search` or `inspect_all_chunks` against their `patient_id` — a
  patient with existing chunks is a follow-up, one with none is new), and
  current queue status (waiting / in-progress / done).
- **"Notify" button**: lets the doctor (or their staff) manually trigger a
  notification to the next patient in line — e.g. "5 minutes, please head to
  Room 304." This is the actual mechanism behind the smart queue concept —
  it doesn't need a complex auto-estimation algorithm yet, a manual trigger
  the doctor/staff presses is enough for the hackathon demo.
- **Patient lookup + vault view**: search/select any patient they have an
  appointment with, view their full vault (reuse the same vault component
  patients see, but framed for clinical review — surface `diagnosis` and
  `medication_history` chunks most prominently since that's what a doctor
  needs fastest mid-consultation).
- **Upload for patient**: upload a document (scan, report, prescription)
  directly into a selected patient's vault. This goes through the same
  `ingest_document()` (or `imaging.ingest_scan()` for actual scan images)
  pipeline as patient self-uploads, tagged with `uploaded_by` = this
  doctor's ID, and should appear in that patient's "Documents from your
  care team" section.

## TPA / Insurance Desk experience (new)

- **Patient lookup**: select a patient (likely one currently admitted or
  with an upcoming admission).
- **Upload for patient**: upload insurance documents, pre-authorization
  letters, cashless approval paperwork, claim status documents — same
  ingestion pipeline, tagged `uploaded_by` = this TPA staff member's ID.
- **Claims/coordination view**: a simple list of patients this desk is
  currently handling and the status of their insurance coordination (e.g.
  pending pre-auth, approved, documentation needed) — keep this as a basic
  status tracker, not a full claims engine.

## Lab / Diagnostics experience (new)

- **Patient lookup**: select a patient who has pending or completed lab
  work.
- **Upload for patient**: upload test results, reports — same ingestion
  pipeline, tagged `uploaded_by` = this lab staff member's ID. For actual
  scan images (not text reports), use `imaging.ingest_scan()` instead of
  `ingestion.ingest_document()` so it goes through Gemini Vision description
  + BioViL-T flagging.
- **Pending work list**: simple list of test/scan orders awaiting upload —
  doesn't need to be sophisticated, a basic status list is enough.

## Hospital Admin / Front Desk experience (new)

This is the role that makes the **Hospital Intake Automation** pipeline real:

```
Patient arrives → Planner → Retrieve old documents → Retrieve allergies →
Retrieve medications → Retrieve insurance → Generate intake form →
Human verification (admin checks) → Admission complete
```

- **Today's admissions/arrivals list**: patients with scheduled admissions
  or appointments today.
- **Generate intake form**: select a patient, trigger generation of an
  admission summary pre-filled from their existing records — allergies,
  current medications, insurance details, past diagnoses (pull from
  `ingestion.extract_fields()`-derived metadata already stored on their
  chunks, plus whatever `retrieval.rag_query()` can surface for a query like
  "summarize allergies and current medications for this patient"). Every
  field must be clearly editable, and there must be an explicit "verify and
  confirm" action — **never auto-finalize without human review.** This is
  the single most important non-negotiable behavior in this entire app:
  the whole point is the admin "simply checks it" rather than re-typing
  everything from scratch, not that the system silently submits something.
- **Cross-department visibility**: admin should be able to see status from
  TPA/insurance and lab/diagnostics for a given patient's admission (e.g.
  "insurance: approved", "labs: pending") so they have one place to confirm
  everything is ready before finalizing intake — this is the "admin simply
  checks it" idea extended across departments, not just documents.
- **Mark admission complete**: once verified, mark the patient as admitted.
  This is what should make the patient's own pre-visit "formalities" flow
  (described in the Patient section above) show as complete on their end.

## Data model — what you need to design

ChromaDB already exists for chunk/embedding storage, scoped by `patient_id`.
You need a **separate, simple database** for everything else: user accounts,
roles, doctor schedules, appointments, queue state, admission status, and
upload provenance (`uploaded_by`). Use whatever free, low-setup option fits
a hackathon timeline — SQLite is the simplest (zero external dependencies,
file-based, fine for a demo with limited concurrent users) and is a
reasonable default unless you have a strong reason to prefer something else
(e.g. Supabase free tier if you want built-in auth + a hosted Postgres with
minimal setup). Make this choice and tell me what you picked and why before
writing the schema.

Rough entities you'll need, at minimum:
- **Users** (id, role, role_subtype if staff, name, contact info,
  role-specific fields like doctor schedule/department/room)
- **Appointments** (id, patient_id, doctor_id, scheduled_time, type —
  OPD consultation vs admission, status)
- **Queue state** (appointment_id, checked_in_at, position, status —
  waiting/in-progress/done, notified_at)
- **Admission/intake records** (patient_id, appointment_id, status per
  department — insurance/labs/documentation, verified_by, verified_at)
- **Upload provenance** — extend whatever metadata you can attach when
  calling `ingest_document()`/`ingest_scan()` with `uploaded_by` (user ID of
  whoever uploaded it) so the patient's UI can distinguish self-uploads from
  care-team uploads. Check whether this needs a small wrapper function on
  your side (not a change to `ingestion.py` itself) since the chunk metadata
  schema is defined inside that file.

## Non-negotiable behaviors (carry these through every role)

- Never let one patient's data appear in another patient's results — every
  document/chunk/appointment/admission record must be scoped by `patient_id`.
- Never auto-finalize the intake form or any administrative action — always
  an explicit human verification step.
- Never present AI-generated answers (Ask HeyDoc, imaging descriptions) as a
  clinical diagnosis — always frame as informational with a visible path to
  a real doctor.
- Every uploaded document must be traceable to who uploaded it
  (`uploaded_by`), even when it's a doctor/lab/TPA uploading on a patient's
  behalf.

## What NOT to build right now

- Don't build real wait-time *estimation* algorithms — a manual "Notify"
  button triggered by staff is sufficient for the demo.
- Don't build a real insurance claims engine or payment processor — basic
  status tracking (pending/approved/needs info) is enough.
- Don't modify `ingestion.py`, `retrieval.py`, or `imaging.py`.

## First step

Before writing code: read the three backend files in full, propose (a) the
frontend/backend stack, (b) the account database choice and schema, and (c)
the page/route map for all four roles. Wait for my confirmation before
scaffolding anything.
