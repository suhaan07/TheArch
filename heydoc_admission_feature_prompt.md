# HeyDoc — New feature: Admission tab (pre-admission, agentic AI verification, advance payment, token)

## Context

HeyDoc already exists as a working multi-role web app (Patient, Doctor,
TPA/Insurance Desk, Lab/Diagnostics, Hospital Admin). Read the existing
codebase fully before starting — this is an **additive feature**, not a
rebuild. Don't restructure existing pages, navigation, auth, or the
ingestion/retrieval backend modules (`ingestion.py`, `retrieval.py`,
`imaging.py`) — those stay untouched.

## The problem this feature solves

Real personal motivation behind this: a patient who has a hospital
admission scheduled (e.g. for surgery) currently shows up and waits **up to
an hour** just on paperwork and documentation before they're actually
admitted to a bed — even though the appointment was already booked. None of
that paperwork needs to happen at the hospital in person. It can all be
done beforehand. The whole point of this feature is: **a patient should be
able to walk in, show one token/OTP, and go straight to their bed** — no
queueing for admission desk processing.

## What to build: a new "Admission" tab in the patient's navigation

This sits alongside the existing Patient nav items (Dashboard, Upload
Documents, Ask HeyDoc, Appointments, My Queue) as a new entry, only visible
once a patient has a scheduled appointment of type "admission" (this
already exists as a concept in the current appointments data — an
admission-type appointment is different from a routine OPD consultation).

### Step 1 — Patient enters admission details

- Admission date (should default to/match the date of their booked
  admission-type appointment, but editable in case it's a separate flow).
- Upload the required documents for this admission. Based on real Indian
  hospital admission practice, the required document set is:
  - **Identity**: a government photo ID (Aadhaar, PAN, Voter ID, or
    passport)
  - **Medical**: doctor's prescription / admission letter stating reason
    for hospitalization, plus any relevant past medical records or
    investigation reports
  - **Insurance** (only if the patient is using cashless/TPA, give them a
    toggle for "self-pay" vs "insurance/TPA cashless" — the required set
    differs):
    - Health insurance card or policy copy
    - A filled cashless pre-authorization request form (this can be a
      structured in-app form rather than a literal uploaded PDF — capture
      the fields a real pre-auth form needs: policy number, sum insured,
      estimated treatment cost, diagnosis/reason for admission, expected
      length of stay, room category requested)
    - KYC of the policyholder (PAN + address proof) — flag in the UI that
      this becomes mandatory if the estimated treatment cost is ₹1 lakh or
      more
    - If it's a corporate/group policy: employee ID card
  - All of this reuses the **same upload pipeline** the rest of the app
    already uses for documents going into a patient's vault — these admission
    documents should also be ingested and chunked the same way, tagged with
    a `doc_type` that marks them as admission-related (e.g.
    `admission_intake`, `insurance_preauth`) so they show up correctly in
    the patient's existing document view too, not just in this new flow.

### Step 2 — Two-tier verification: rules first, AI only where rules can't decide

This is the agentic core of the feature, and the actual hackathon
differentiator. The key design decision: **don't reach for an LLM call by
default.** Most of this checklist is decidable with plain rule-based logic
against fields the existing pipeline already extracts — that's deterministic,
free, instant, and you can show a judge exactly why something passed or
failed. Only escalate to Gemini for the genuinely fuzzy cases language
rules can't cleanly express. Build it as two explicit tiers, not one
LLM-first pass.

**Tier 1 — rule-based checks (no AI call, run first, resolves most items):**

- Every document the patient uploads in Step 1 already goes through the
  existing OCR pipeline (`ingestion.py`'s hybrid OCR: PyMuPDF → docTR →
  Gemini Vision escalation) and the existing document classifier
  (`classify_document()`), exactly like any other upload. No new OCR work
  needed — reuse what's already built and tested.
- Identity document present → does any uploaded doc classify as
  `identity_proof` (extend the classifier with this doc type if it doesn't
  exist yet — check what's already there first), or does extracted text
  match an ID-number-shaped pattern (Aadhaar/PAN format regex)?
- Insurance policy document present → does any doc classify as `insurance`?
- KYC present → does a doc match a PAN/address-proof pattern?
- PAN-mandatory threshold → plain numeric comparison:
  `if estimated_cost >= 100000 and no PAN-pattern document found: flag as missing`.
  This is just a number check against the cost the patient entered in
  Step 1 — no reasoning required.
- All required docs present for the chosen path → a checklist of doc_types
  needed (from the self-pay vs insurance toggle) compared against doc_types
  actually present. Pure set comparison.
- Each of these resolves immediately and deterministically to `verified` or
  `missing` — no Gemini call involved. This should cover the large majority
  of checklist items in normal cases.

**Tier 2 — Gemini reasoning (only called for items Tier 1 can't resolve):**

Escalate to Gemini only for checks that are genuinely semantic, where regex
or exact matching would be too brittle to write reliably:

- Does the diagnosis/reason extracted from the doctor's prescription
  actually correspond to the admission reason the patient typed in Step 1?
  (e.g. "recurrent dermoid cyst" vs "nose surgery" — same condition, worded
  differently — a keyword match would false-flag this constantly)
- A document classified correctly but its extracted date/field is missing
  or garbled (common with handwritten-note OCR) — is this actually invalid,
  or did extraction simply fail to find a field that's present in the
  document? Gemini can look at the raw extracted text and make this call
  in a way a fixed regex can't.
- Anything Tier 1 marks ambiguous because a document doesn't cleanly match
  any expected doc_type but also isn't clearly wrong.

For these cases only, ask Gemini to look at the extracted text/fields for
that specific document and the specific checklist item it's being checked
against, and return a verdict plus a short plain-language explanation the
patient can act on if it doesn't pass (e.g. "we couldn't confirm your PAN
card was uploaded — please add it" rather than a raw error code).

**Combined output:** every checklist item ends in one of three states —
`verified` (Tier 1 or Tier 2 confirmed it) / `missing` (Tier 1 confirmed
it's absent) / `needs_review` (Tier 2 genuinely couldn't decide). Tier 2
itself should rarely produce `needs_review` — that's reserved for cases
where even Gemini's reasoning comes back uncertain, which should be rare.
When `needs_review` items do occur, surface them to the **Hospital Admin**
role (not TPA — keep this internal to hospital staff rather than
introducing an insurance-desk dependency for something the rules+AI layer
should mostly resolve on its own) as a short manual check.

The patient sees real-time per-item status on their Admission tab —
e.g. "Identity: verified", "Insurance policy: verified", "PAN card: missing
— please upload" — updating as each item resolves, not a single
pending/approved binary. If every item the system can check comes back
`verified` with zero `needs_review` items, the patient proceeds straight to
payment without any human ever touching their case. That's the actual
point: most of the verification work happens through rules-plus-targeted-AI
reasoning, with a human only in the rare genuine exception, not a default
queue.

### Step 3 — Advance payment and booking confirmation

- Once all required items for the chosen payment path are verified, unlock
  an "advance payment" step for the patient. For a hackathon demo, a real
  payment gateway integration is not necessary — build this as a clearly
  mocked payment step (e.g. a confirm button simulating successful payment,
  or a placeholder Razorpay/Stripe-style UI if you want it to look
  realistic, but don't wire actual payment processing).
- After the advance payment step is marked complete, generate a **booking
  confirmation with a unique token/OTP** for this admission. This token is
  the single artifact the patient needs to bring to the hospital — it
  should be displayed prominently (large, easy to read/screenshot, maybe
  also offer a QR code representation if convenient) along with the
  admission date and any other essential confirmation details (which
  doctor, which department).

### Step 4 — Token redemption at the hospital

- On the **Hospital Admin** role's side, add a way to redeem this token —
  e.g. an input field where front-desk staff enter or scan the
  patient's token/OTP, which pulls up that patient's already-verified
  admission record (no need to re-check documents, they're already
  verified — this is the entire point) and lets the admin mark the patient
  as "arrived, bed assigned" in one action.
- This should connect to whatever bed/ward assignment concept makes sense
  given the existing admin intake form feature — if a bed/ward field
  doesn't already exist there, add a simple one (e.g. ward name + bed
  number, manually entered by admin at the point of redemption, not
  auto-assigned by any algorithm).

## Non-negotiable behaviors (consistent with the rest of the app)

- Tier 1 (rules) always runs first for every checklist item — never call
  Gemini for something a plain doc_type check or regex/numeric comparison
  can already decide. Tier 2 is the exception path, not the default path.
- Every `verified` determination, whether from Tier 1 or Tier 2, must be
  traceable back to a specific uploaded document and what was extracted
  from it — never mark something verified without a concrete source to
  point to if asked. This mirrors the citation requirement already
  expected elsewhere in the RAG pipeline.
- `needs_review` is the only path that pulls in a human (Hospital Admin) —
  the system should never silently mark something verified when it's
  actually uncertain, and it should never block the patient on a human
  review for something Tier 1 or Tier 2 could resolve on its own.
- Never let the token/OTP be guessable or reused after redemption — once
  redeemed at the hospital, it should be marked as used and not valid for
  reuse.
- All admission documents must remain scoped to the correct patient_id,
  exactly like every other document in the system — no cross-patient
  visibility.
- If a checklist item comes back missing or needs_review, the patient must
  be able to see specifically what's missing or unclear and re-upload
  corrected documents — don't leave them stuck without knowing why.
- Never auto-unlock payment if any required checklist item is still
  `missing` — only `verified` items (with any `needs_review` items resolved
  by admin) allow the flow to proceed.

## What NOT to build right now

- No real payment gateway integration — mock it.
- No real OTP delivery via SMS/email — generating and displaying it in-app
  is sufficient for the demo.
- No bed-management/ward-availability system — admin manually enters
  ward/bed at redemption time, no inventory tracking needed yet.
- No new ML model for document verification — Tier 1 is plain rule-based
  logic (doc_type checks, regex, numeric comparisons) against fields the
  existing classifier/OCR pipeline already extracts. Tier 2 is Gemini
  reasoning over that same extracted data for the handful of genuinely
  semantic checks — not a separately trained classifier either way.

## First step

Before writing code: review how the existing document classification
(`classify_document`, `extract_fields` in `ingestion.py`), the Patient nav,
and the Admin intake form are currently structured, then propose (a) where
this new Admission tab's data lives (extending the existing
appointments/admission data model vs a new entity), (b) the exact checklist
schema and which items you'd put in Tier 1 (rules) vs Tier 2 (Gemini) and
why, and (c) how `needs_review` items get surfaced into the Admin role's
existing views. Wait for confirmation before building.
