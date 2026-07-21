# PRD — Invoice Processing Automation (Zamp ASA Case Study, PS-1)

## 0. Context for Claude Code

You are building this end-to-end inside VS Code via Claude Code. This is a 1-week take-home case study for an AI Solutions Associate role. The grading criteria are:
1. The process actually **runs live** on real inputs (not a mockup).
2. Edge cases are **deliberately designed**, not ignored.
3. There is an intuitive UI with a **live run view** + **dashboard** (history/status/outputs).
4. I can explain every design decision fluently in a live interview demo.

**Do not build a simulation or a UI that fakes execution.** Every stage shown in the run view must correspond to a real function call that actually executed.

### Permissions — read this first
I don't want to be asked for permission on every file write / bash command / test run during this build. Set up the project so routine dev actions are pre-approved and only genuinely risky actions (deleting files outside the repo, pushing to git, hitting external network endpoints beyond what's whitelisted, installing global packages) still prompt.

At the start of this session, create `.claude/settings.json` in the project root with:

```json
{
  "permissions": {
    "allow": [
      "Read",
      "Write(./**)",
      "Edit(./**)",
      "Bash(python:*)",
      "Bash(pip install:*)",
      "Bash(pip install --break-system-packages:*)",
      "Bash(pytest:*)",
      "Bash(npm:*)",
      "Bash(node:*)",
      "Bash(mkdir:*)",
      "Bash(ls:*)",
      "Bash(cat:*)",
      "Bash(git status)",
      "Bash(git diff)",
      "Bash(git add:*)",
      "Bash(git commit:*)"
    ],
    "deny": [
      "Bash(rm -rf /*)",
      "Bash(git push:*)",
      "Bash(sudo:*)"
    ],
    "defaultMode": "acceptEdits"
  }
}
```

This uses `acceptEdits` mode (auto-approves file reads/writes/edits inside the project, still asks before arbitrary/unlisted bash commands) plus an explicit allow-list for the bash commands this build actually needs (python, pip, pytest, npm, node, git add/commit, basic file inspection). Git push and destructive commands stay gated intentionally — I'll approve those manually. If you (Claude Code) hit a permission prompt for something clearly routine to this build (e.g. running the dev server, running the test suite, installing a package already in requirements.txt), add it to the allow list in `.claude/settings.json` rather than asking me each time — just tell me afterward what you added and why.

Do not enable full `bypassPermissions` / `--dangerously-skip-permissions` — I still want a stop on anything touching `.git`, network calls to unfamiliar hosts, or global system changes.

---

## 1. Problem

A mid-size company receives hundreds of vendor invoices monthly, all as PDFs via email. AP staff manually open each one, find the matching PO in a spreadsheet, check the numbers, and decide what to do. Invoices are inconsistent: some are clean text PDFs, some are scanned images; line items may be itemized or bundled; tax may be embedded or separate; PO references may be explicit, implied, or missing; some invoices are missing critical fields entirely.

**Goal:** build a process that takes an invoice as input and produces a clear, reasoned decision as output, with every intermediate step visible, and handles the messy edge cases gracefully.

## 2. Scope

### In scope
- Ingest a single invoice (PDF) per run, from the UI (drag/drop or file picker) or a `POST /api/invoices` endpoint.
- Extract structured fields from the PDF (invoice number, date, vendor name, line items, subtotal, tax, total, PO reference if present).
- Load a mock PO/vendor dataset (approved vendors, PO amounts, tolerance thresholds).
- Match invoice → PO using vendor name + PO reference + amount tolerance logic.
- Run duplicate-invoice detection against prior runs.
- Produce one of: **Auto-Approve**, **Needs Review**, **Reject**, each with a plain-language reason and the evidence trail.
- Live run view: shows each pipeline stage (Extract → Validate → Match → Decide) as it executes, with intermediate output at each stage.
- Dashboard: history of all runs, status, extracted summary, decision, timestamp; click into any run to see full trace.
- 3 realistic synthetic edge cases (see §5), each independently re-runnable from the dashboard.

### Out of scope
- Multi-invoice batch upload (single-invoice-at-a-time is fine for the demo).
- Real payment execution / ERP integration.
- User auth / multi-tenant support.

## 3. Architecture

```
[UI: Upload] → [FastAPI backend]
                     │
                     ▼
            ┌─────────────────┐
            │  1. EXTRACT     │  PDF → structured JSON
            │  (text PDFs:    │  - pdfplumber/pymupdf for text-native PDFs
            │   direct parse; │  - vision-capable LLM call (Claude) for scanned/
            │   scanned:      │    image PDFs, or when text extraction confidence
            │   vision LLM)   │    is low
            └────────┬────────┘
                     ▼
            ┌─────────────────┐
            │  2. VALIDATE    │  - required fields present?
            │                 │  - totals reconcile (subtotal + tax = total)?
            │                 │  - confidence score per field
            └────────┬────────┘
                     ▼
            ┌─────────────────┐
            │  3. MATCH       │  - look up vendor in mock vendor DB
            │                 │  - find candidate PO(s) by vendor + PO ref
            │                 │  - handle split-PO / multi-invoice-per-PO case
            │                 │  - amount-tolerance check (e.g. ±2% or ±$50)
            └────────┬────────┘
                     ▼
            ┌─────────────────┐
            │  4. DECIDE      │  - rules engine, NOT free-form LLM judgment,
            │                 │    for the actual approve/reject call
            │                 │  - LLM used only to draft the human-readable
            │                 │    explanation of the rules-engine outcome
            └────────┬────────┘
                     ▼
            [Store run in SQLite] → [Dashboard reads from SQLite]
```

**Why a deterministic rules engine for the final decision, not an LLM call:** matches the pattern I already used in the customer-support-agent build (SafetyGuard) — the decision needs to be auditable and explainable to a non-technical AP buyer without "the model felt like it." The LLM's job is extraction (messy input → structured data) and explanation (structured decision → plain English), never the approve/reject judgment call itself. Be ready to justify this split explicitly in the interview.

## 4. Tech stack

- **Backend:** Python, FastAPI
- **Extraction:** `pdfplumber` / `pymupdf` for text-native PDFs; fallback to Claude (vision) for scanned/low-confidence PDFs
- **Storage:** SQLite (runs, extracted fields, decisions, PO/vendor mock dataset)
- **Frontend:** React + Tailwind (or plain HTML/JS if faster to ship — prioritize it actually working over framework choice) served via FastAPI static files or a lightweight Vite dev server
- **Live run view:** Server-Sent Events or simple polling of a `/api/runs/{id}/status` endpoint — stream each stage as it completes, don't just show a spinner then a final result
- **Test data generator:** a script to produce realistic invoice PDFs (`reportlab` or similar) + a matching PO dataset (JSON/CSV)

## 5. Edge cases to build (pick 3, build deliberately, don't hand-wave)

1. **Scanned/image-only invoice, no embedded text.** Forces the vision-LLM extraction path instead of direct text parsing. Decision trace should show which extraction method was used and the confidence score.
2. **Split PO — one PO, multiple invoices.** Invoice amount alone doesn't reconcile against the PO total; system must recognize partial billing against a PO and check cumulative invoiced-to-date against PO amount, not just this invoice vs. PO.
3. **Missing/ambiguous PO reference with amount mismatch beyond tolerance.** No explicit PO number on the invoice; system attempts vendor+amount fuzzy match, finds a candidate but amount is outside tolerance → routes to **Needs Review** with the candidate match and specific discrepancy called out, not just "no match found."

(A 4th optional edge case — duplicate invoice submission — is a good stretch goal if time allows, since duplicate detection is explicitly named in the problem statement.)

## 6. UI requirements

- **Upload view:** drop a PDF in, hit run.
- **Live run view:** 4 stages (Extract/Validate/Match/Decide) visibly light up / complete in sequence with the actual intermediate JSON output shown at each stage, not just a checkmark. This is the part that proves it's not a mockup.
- **Result view:** decision (color-coded: green/yellow/red), plain-English reasoning, evidence (extracted fields, matched PO, tolerance calc).
- **Dashboard:** table of all past runs — vendor, invoice #, date run, decision, status. Click a row to reopen that run's full trace.

## 7. Build order (Days 2–6 from the case study schedule)

1. Test data: build 5–6 synthetic invoices (mix of clean text + 1 scanned image) + matching PO/vendor dataset.
2. Extraction stage working end-to-end on the happy path.
3. Validate + Match + Decide stages, happy path only, rules engine hardcoded first.
4. Wire up SQLite storage + dashboard read view.
5. Build the live run view (this is UI-heavy — budget real time for it, it's part of the grade).
6. Add the 3 edge cases one at a time, confirm each is independently demoable.
7. Record the 5-minute Loom: happy path + at least one edge case, narrate the extraction→validate→match→decide reasoning at each step.

## 8. Definition of done

- [ ] `python main.py` (or equivalent) starts the app with no manual setup beyond `pip install`
- [ ] Upload a real PDF → live run view shows all 4 stages executing with real intermediate output
- [ ] Dashboard shows run history, clicking a row reopens the full trace
- [ ] All 3 edge cases produce a materially different outcome/reasoning path than the happy path, and are re-runnable on demand
- [ ] Every decision includes a plain-language explanation a non-technical AP person could act on
- [ ] I can explain, live, why the decision engine is rules-based rather than LLM-judgment-based
