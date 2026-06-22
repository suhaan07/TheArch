# HeyDoc (TheArch)

A healthcare RAG application built for an IIT KGP hackathon, by a 2-person
team. Patients keep a single longitudinal medical vault; doctors, labs,
TPAs (insurance desks), and hospital admins interact with that vault
according to real hospital-style access rules.

**Live**: [frontend](https://suhaan07.github.io/TheArch/) ·
backend on Railway (`backend-production-239e.up.railway.app`)

---

## What it does

Five roles, one shared patient vault:

- **Patient** — uploads/owns their own documents, books appointments,
  checks into the live queue, chats with "Ask HeyDoc" (RAG over their own
  records), and for admission-type appointments completes pre-admission
  paperwork from home.
- **Doctor** — sees only patients with an accepted-or-later appointment
  with them, manages their queue, uploads on a patient's behalf.
- **Lab / TPA (insurance desk)** — sees patients via hospital-matching
  (same hospital as the patient's doctor), uploads results/insurance docs.
- **Hospital admin** — same hospital-matching access, plus the admission
  pipeline: `needs_review` resolution and token redemption (checking a
  pre-verified patient straight into a bed).

The pitch: a patient's medical history shouldn't live in scattered paper
files re-explained at every visit, and hospital admission shouldn't cost an
hour of in-person paperwork when it can be done from home and verified
automatically.

---

## Tech stack

**Backend**: FastAPI + raw `sqlite3` (no ORM) — `server.py` is the entire
HTTP surface.

**Frontend**: Vanilla JS, zero build step, zero framework — `web/app.js` is
a single-file SPA (one global `state`, one `render()`). Polling (not
WebSockets) for live updates.

**RAG pipeline**: ChromaDB (patient-scoped chunks) + `BAAI/bge-large-en-v1.5`
embeddings + BM25 → RRF fusion → `BAAI/bge-reranker-v2-m3` cross-encoder
reranking → Gemini (`gemini-2.5-flash-lite`) generation, with a rule-based
query router (`advanced_rag.py`) in front so Gemini is only invoked on
routes that actually need it.

**OCR pipeline**: hybrid plaintext → PyMuPDF (digital PDF text layer) →
docTR → Gemini Vision escalation, with confidence-aware image
preprocessing (`preprocessing.py`) and a garbage-detection check that
overrides reported OCR confidence when a read looks confidently wrong.

**Imaging pipeline** (`imaging.py`): separate from document OCR — Gemini
Vision describes raw scan images (X-ray/CT/MRI/ultrasound), with optional
BioViL-T zero-shot phrase scoring for chest X-rays.

**Document authenticity** (`id_validators.py`): Verhoeff checksum for
Aadhaar, PAN holder-type validation, EPIC/passport format checks, an
insurance structure heuristic, and a doctor registration-number check —
raises the bar against careless fakes; not a substitute for an official
government/insurer lookup API (none integrated).

---

## Running locally

```bash
pip install -r requirements.txt
```

Create `.env` in the project root:

```
GEMINI_API_KEY=your-key-here
```

Start the backend:

```bash
uvicorn server:app --reload --port 8000
```

Serve `web/` with any static file server (e.g. `python -m http.server` from
inside `web/`) and open it in a browser — `app.js` auto-detects `localhost`
vs. production by hostname, so no config is needed to point it at the local
backend. First request after a cold start takes a while (embedder +
reranker + docTR all load lazily on first use).

---

## File map

```
server.py            FastAPI app — every endpoint, DB schema/migrations
ingestion.py          Document OCR + chunking + embedding + classification
retrieval.py          Hybrid search, reranking, RAG answer generation
advanced_rag.py        Query router sitting in front of retrieval.py
imaging.py            Scan image (X-ray/CT/MRI) description pipeline
preprocessing.py       Confidence-aware OCR image preprocessing
ocr_evaluation.py      Evaluation harness for the preprocessing pipeline
admission.py          Tier1/Tier2 pre-admission verification engine
id_validators.py       Aadhaar/PAN/insurance/prescription authenticity checks
scripts/quantize_models.py   One-time: INT8-quantize + push models to HF Hub (dormant — see below)
web/index.html, styles.css, app.js   The entire frontend
heydoc.db              SQLite (gitignored)
data/                  uploads/, chroma_db/ (gitignored)
.env                   GEMINI_API_KEY, HF_TOKEN (gitignored)
```

---

## Design notes worth knowing before changing anything

- **Tier1 → Tier2 → needs_review escalation** (`admission.py`):
  deterministic check first, Gemini only for genuinely ambiguous/semantic
  cases, human review only when Gemini itself can't decide. Never silently
  auto-verifies an uncertain result.
- **Hybrid OCR with a safety net, not a single tool**: plaintext → PyMuPDF
  → docTR → Gemini Vision, with garbage-detection overriding reported
  confidence on a confidently-wrong read.
- **Hospital-scoped authorization as one function**: every TPA/lab/admin
  access check goes through `authorize_patient_access()`, never
  reimplemented per-endpoint.
- **All-naive-local timestamps** — never mix `datetime.utcnow()` with
  anything appointment/queue-related; this has caused a real bug before.
- **Never echo secrets** — API keys are read from `.env` or piped via
  stdin, never typed into a command string or printed.

---

## Deployment

**Frontend**: GitHub Pages, deployed via a GitHub Actions workflow
(`.github/workflows/pages.yml`) on every push to `main` touching `web/`.

**Backend**: Railway, Hobby plan, persistent volume mounted at `/data`
(SQLite + ChromaDB + uploads). Runs the full, non-quantized pipeline —
identical to local dev. The GitHub↔Railway auto-deploy connection is
currently broken (repo access lost from Railway's side), so deploys go
through `railway up` directly rather than deploy-on-push.

**Quantization infra** (`scripts/quantize_models.py`, the
`THEARCH_QUANTIZED` env var in `ingestion.py`/`retrieval.py`): built during
an earlier phase when the backend ran on Railway's free 1024MB tier and the
full model stack (~3.5GB) didn't fit. After upgrading to the Hobby plan
with more memory, this is no longer needed and is currently dormant —
`THEARCH_QUANTIZED` is unset in production, so the code path it gates
never runs. Left in place rather than deleted in case memory constraints
come up again.

---

## Known limitations

- TPA "Claims tracker" and Lab "Pending work" still run on the original
  hardcoded mock data from the initial JSX conversion — never wired to
  real data.
- Document authenticity checks raise the bar against careless fakes; they
  are explicitly **not** proof of genuine government/insurer/hospital
  issuance — no official lookup API is integrated.
