# CentrAlign AI — Enterprise Document Verification & Processing

CentrAlign AI is an enterprise-grade document processing and verification application built with deterministic guardrails and provenance tracking across a five-stage pipeline:
**Extract → Guardrails → Validate → Match → Decide**.

---

## Data Provenance and Decision Boundaries

- Text extraction records field values with their source and confidence. Heuristic fields are identified as heuristic; missing values remain `null` rather than being filled with defaults.
- Scanned-document extraction uses an optional vision model. Its output is a candidate extraction, not guaranteed truth; model confidence, validation results, guardrail findings, and warnings are included for review.
- Currency is only set when an ISO currency code appears in the document. A dollar symbol alone does not identify USD versus another dollar-denominated currency, so the currency remains missing in that case.
- Vendor and PO matches come only from records in the configured database. The decision engine is deterministic; an LLM does not make the approve/review/reject decision.
- Explicit synthetic examples are available as downloads for testing; downloads are not ingested automatically. The local seed script intentionally loads fixture vendor/PO data for a sandbox demo.

---

## User Interface — Focused Box Layout

The main application delivers a focused, enterprise-grade interface:

1. **CentrAlign AI Branding**: Enterprise header with brand identity, audit engine status, and light/dark theme switch.
2. **Central Document-Upload Box**:
   - Primary interaction element supporting drag-and-drop and a file-picker button.
   - Accepts genuine PDF documents only (up to 15 MB).
   - Pre-flight client-side validation of file extension, non-empty content, size cap, and `%PDF-` header signature.
   - Real-time status display and processing progress indicator.
   - "Upload Another Document" button for continuous workflow.
   - Clear error messages when uploads or checks fail.
   - Zero sample invoices or placeholder transactions cluttering the workspace.
3. **Document-Processing Status Area**:
   - Real-time five-stage execution tracking (`Extract → Guardrails → Validate → Match → Decide`).
   - Execution duration in milliseconds per stage and real summary badges.
4. **Structured Results Table**:
   - Detailed tabular view displayed only when actual results are available.
   - Categorizes every field as `EXTRACTED`, `CALCULATED`, `MATCHED`, `MISSING`, or `UNCERTAIN`.
   - Fields: Invoice Number, Vendor Name, Invoice Date, PO Reference, Subtotal, Tax, Total, Extraction Quality, Validation Status, Vendor Matching, PO Matching, Final Decision, and Explanation & Evidence.
5. **Decision & Evidence Section**:
   - Outcome Banner: **AUTO-APPROVE** (green), **NEEDS REVIEW** (amber), or **REJECT** (red).
   - Complete **Deterministic Rules Engine Evaluation Matrix** (`R0` through `R8`) with evaluation state, impact, and audit detail.
   - Expandable Per-Stage Audit Inspector with raw payload inspection.
6. **Processing Run Audit Log**:
   - Displays genuine persisted records from SQLite (`runs.db`).
   - Reopen any historical run to inspect its complete evidence trail.
   - Clean slate: starts with zero runs when database is fresh.

---

## Five-Stage Processing Pipeline

| Stage | Function | Deterministic Behavior |
|---|---|---|
| **1. Extract** | `pymupdf` (text-native PDFs) or Groq Vision LLM (`qwen/qwen3.6-27b`) for scans | Structured JSON schema; zero hallucinated fields; per-field confidence scores |
| **2. Guardrails** | Prompt-injection scanner (`app/guardrails/prompt_injection.py`) + output bounds | Static pattern scan on all free text; flags injection phrasing; bound-checks amounts |
| **3. Validate** | Completeness & arithmetic verification (`app/pipeline/validate.py`) | Reconciles Subtotal + Tax = Total; line item sums; checks required fields and sanity bounds |
| **4. Match** | Vendor & PO reconciliation (`app/pipeline/match.py`) | Normalized vendor fuzzy similarity; tolerance bounds; cumulative PO split billing |
| **5. Decide** | Deterministic business rules engine (`app/pipeline/decide.py`) | Ordered rule evaluation: `R0` (Injection), `R1` (Duplicate), `R2` (Validation), `R3` (Vendor), `R4` (PO), `R5` (Confidence), `R6` (PO Confirmation), `R7` (Tolerance), `R8` (Cap $25,000) |

Deferred invoice uploads are placed on a single background queue and continue even if no browser is attached to the SSE stream. Each actual stage event is persisted for live streaming/replay. Extraction has a 120-second caller deadline (with a shorter HTTP timeout on vision requests); unhandled run errors are logged and persisted as failed status, error, and failure trace. A stale-run guard marks records still running after 180 seconds as failed and emits a terminal failure event. Completed run records persist the deterministic decision reason, including when a duplicate causes a different outcome from its earlier run.

---

## Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+ (for building the frontend)

### Installation

```bash
# 1. Install backend dependencies
pip install -r requirements.txt

# 2. Configure environment (optional, only needed for scanned PDFs)
cp .env.example .env
# Set GROQ_API_KEY in .env if processing scanned invoices via vision

# 3. Build frontend (prebuilt in ui/dist)
cd ui
npm install
npm run build
cd ..

# 4. Start CentrAlign AI (serves backend + frontend)
python main.py
```

Open **http://127.0.0.1:8000** in your browser.

---

## Automated Verification Suite

Run the comprehensive test suite verifying all 10 core scenarios:

```bash
python -m pytest -v
```

### Verified Scenarios
1. **Valid text-based invoice**: Auto-approves within tolerance (`test_scenario_1_valid_text_invoice`).
2. **Scanned invoice**: Routes to vision extraction, fails cleanly if API key missing (`test_scenario_2_scanned_invoice`).
3. **Missing or uncertain fields**: PO reference omitted on document, flags missing, routes to human review (`test_scenario_3_missing_or_uncertain_fields`).
4. **Prompt-injection attempt**: Detects malicious directive in line item, triggers `R0`, routes to Needs Review (`test_scenario_4_prompt_injection_attempt`).
5. **Unknown vendor or missing purchase order**: Unmatched vendor triggers `R3`, rejects invoice (`test_scenario_5_unknown_vendor`).
6. **Duplicate invoice**: Detects prior run collision, triggers `R1`, rejects duplicate (`test_scenario_6_duplicate_invoice`).
7. **Exceeding auto-approval limit**: Total over $25,000 cap triggers `R8`, routes to Needs Review (`test_scenario_7_invoice_exceeding_auto_approval_limit`).
8. **Invalid or oversized upload**: Enforces PDF header magic bytes `%PDF-`, size cap, and non-empty checks before extraction (`test_scenario_8_invalid_or_oversized_upload`).
9. **Empty database**: Indicates matching cannot be completed without fabricating records (`test_scenario_9_empty_database_indicates_matching_uncompletable`).
10. **Processing failure or unavailable extraction service**: Records failed run accurately, never masks as success (`test_scenario_10_processing_failure_records_as_failed`).
11. **UI branding and provenance wording**: Confirms the product identity and that the removed slogan cards are not present (`test_ui_keeps_branding_without_removed_principle_cards`).

---

## Autonomous Task Worker

The app also provides a natural-language task worker in the main UI. This is a deliberately narrow, executable prototype rather than a general computer-use agent. Its supported workflow is invoice discovery and processing in the local sandbox:

1. A user enters an invoice goal. The worker identifies the vendor/invoice reference and whether recording was requested; extract-only requests never write to the ledger.
2. It searches only PDFs in `data/uploads/`, ranks candidates by relevance and modification time, retries with a broader search if needed, and asks the user to choose when multiple candidates are equally relevant and no “latest” preference was expressed.
3. It runs the same real extraction, prompt-injection guardrail, validation, vendor/PO matching, and deterministic decision pipeline as a direct invoice upload.
4. It hard-stops deterministic `reject` outcomes. `needs_review` outcomes and prompt-injection flags pause for explicit human approval before any record is written. Approval allows recording for review; it does not convert the policy decision to auto-approval or authorize payment.
5. It persists task status, event history, and results in SQLite, and independently checks the resulting invoice run before reporting completion.

Use the **Autonomous task worker** panel on the home page. Upload PDFs through the app first; the worker intentionally does not search fixture directories, arbitrary filesystem locations, or external websites. Task endpoints are available under `/api/worker` (`POST /task`, `GET /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/stream`, `POST /tasks/{id}/clarify`, `POST /tasks/{id}/approve`, and `POST /tasks/{id}/cancel`). Blocked tasks expose their policy reason and a cancel action; cancellation does not override the policy decision. Unsupported non-invoice goals are explicitly declined.

For manual upload testing, `GET /api/examples` lists three curated synthetic PDFs and their expected behavior; each `download_url` returns the file as an attachment. Downloads never create a run. For the happy path to auto-approve, seed the local fixture vendor/PO data first with `python scripts/seed_local_db.py` and ensure the invoice is not already in run history.

### Worker safety and outcome semantics

- A completed worker task means the requested invoice record was persisted and verified. The evidence field `payment_approved` separately states whether the deterministic decision was `auto_approve`.
- A verified `needs_review` record is not a payment approval. A rejected invoice is not ingested.
- A user rejection at an approval checkpoint becomes terminal and cannot be restarted by reconnecting to the stream.
- Clarification and approval decisions are tied to the candidate file and SHA-256 content observed at the checkpoint; changed or out-of-scope files are refused on resume.
- The verifier does not treat an unextracted requested field as a successful match; it reports persisted status separately from unverified fields.
- The worker only has local uploaded-file and internal SQLite tools; it does not control a desktop, browse arbitrary websites, send payments, or write to an external ERP.
- The task planner/intent parser is deterministic and invoice-specific. The optional Groq vision model is used only for scanned-PDF extraction, not for planning or business decisions.

### Local demo walkthrough

1. Start the app using the instructions above and open `http://127.0.0.1:8000`.
2. Upload a genuine invoice PDF (or create a local synthetic invoice using the project test-data script and upload it yourself). For a fixture-only local demo, explicitly seed the synthetic vendor/PO data with `python scripts/seed_local_db.py`; this is optional, writes fabricated fixture records into your local database, and is never done by app startup. For real use, load your own authorized vendor/PO data instead.
3. Enter a goal in the Autonomous task worker panel. Inspect the emitted plan, observations, decision, and verification evidence.
4. For a review-path demonstration, upload a test invoice with prompt-injection text or a deterministic `needs_review` condition, request processing, inspect the pause, then approve or reject it.
5. Reopen the task from task history and show that its evidence survives a page refresh or backend restart.

No demo video or hosted live demo is included in this source workspace. Record and link a short walkthrough before submission; do not claim a hosted demo exists until one is actually published.

---

## Architecture and Design Decisions

- **One deterministic invoice pipeline:** Both direct uploads and worker tasks call the same five real stages; there is no second set of mocked extraction or decision logic.
- **Rules, not an LLM, decide financial outcomes:** Final decisions must be repeatable, auditable, and attributable to explicit policy rules. The optional vision model converts scanned page content into candidate fields only; the guardrails and validation logic check those fields, and deterministic rules choose the outcome.
- **Human approval is a boundary, not a bypass:** Review and injection cases stop before the write tool. Approval allows a review item to be recorded for human follow-up. It does not override a `reject` or mutate a `needs_review` decision to `auto_approve`.
- **Evidence-first completion:** A persisted run is queried back from SQLite before the worker reports completion. The response distinguishes record persistence from payment approval.
- **Constrained tool surface:** The worker searches only `data/uploads/` and can write only through the app's own invoice-run persistence path. It cannot browse arbitrary sites, access credentials, or make payments.
- **Durable audit trail:** Worker tasks and their events/results live in the same SQLite database as invoice runs. Stream reconnects replay stored events; terminal tasks do not execute again.

### Frameworks and external services

- Python 3.10+, FastAPI, Pydantic, SQLite, PyMuPDF, and pytest for the backend, extraction, persistence, API, and tests.
- React 19, TypeScript, Vite, Tailwind CSS 4, and Lucide icons for the UI.
- Groq's API is optional and used for vision extraction of scanned PDFs only; configure `GROQ_API_KEY` and optionally `GROQ_MODEL`. Text-based extraction and the worker do not require this service. No third-party website, company system, payment rail, or live credential is used.
- ReportLab and Pillow support generating local synthetic test documents. Synthetic fixtures are test/demo materials and must be explicitly uploaded to enter the worker's user-upload boundary.

### Assumptions

- The prototype's supported task domain is invoice discovery and recording, not arbitrary office work.
- “Latest” refers to the newest matching PDF modification time among the app's uploaded documents; a task with a specified invoice ID favors a direct filename match.
- Recording a `needs_review` invoice after human approval creates an auditable review record, not an approved payable.
- Vendor and purchase-order data must be loaded explicitly into the local database; fresh installs do not invent master data.
- Uploaded documents and SQLite are local prototype storage, not production-grade encrypted or multi-tenant systems.

### Known limitations

- Natural-language understanding is a small deterministic parser; it does not use an LLM planner and only understands the invoice workflow and a limited set of vendor/identifier phrasings.
- Candidate discovery is limited to filenames in `data/uploads/`; it does not inspect email, cloud drives, arbitrary folders, websites, or other applications.
- “Latest” is based on filesystem modification time, not an invoice date extracted from every candidate. Ambiguity clarification only applies to equally ranked candidates; it is not a semantic duplicate/document-understanding system.
- The worker uses a single in-process background queue and SQLite. It is not built for concurrent multi-user deployment, process clusters, distributed queues, auth, tenant isolation, or production retention/monitoring.
- The approval endpoint re-runs deterministic extraction and checks before performing the write, rather than persisting a resumable execution checkpoint. It records the decision in the audit events but has no user identity/authentication.
- No actual accounting-system/ERP write or payment occurs. “Internal system” means this prototype's SQLite-backed invoice run ledger.
- Vision availability, scan quality, multi-page handling, and extraction correctness depend on the configured model/service and the extraction checks; all extracted data still requires appropriate human review.
- A public repository URL and demo recording are delivery artifacts to add when available; they are not fabricated by this codebase.

### What to build next

1. Add authenticated, role-aware approval with immutable reviewer identity, comments, and persisted resumable checkpoints.
2. Expand the narrow action parser into a richer typed task-intent model and explicit tool registry, while retaining strict action authorization and deterministic accounting policies.
3. Scale the in-process run queue into durable distributed execution, and add idempotency keys, transactional duplicate constraints, and concurrency-safe run/PO accounting.
4. Add a guarded master-data import/validation interface and rank candidate recency using extracted invoice dates with user confirmation for close ties.
5. Add structured observability, retention controls, encrypted storage, adversarial evaluation, and deployment hardening.
6. With authorization and sandboxing, extend tools to a real test ERP/API connector and verify its read-after-write result; keep payment execution out of scope until separate controls exist.
