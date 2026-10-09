"""FastAPI backend: upload/run invoices, live SSE streaming, run history.

Endpoints:
  POST /api/invoices              upload a PDF; ?defer=1 -> create run only,
                                  background queue executes it automatically
  GET  /api/runs/{id}/stream      SSE: tails persisted pipeline stage events;
                                  finished runs replay the stored trace
  GET  /api/runs                  run history (dashboard)
  GET  /api/runs/{id}             one run incl. full per-stage trace
  DELETE /api/runs                clear history (demo reset)
The static frontend is served at /.

Invoice upload is the only way to feed a PDF into processing. A fixed,
download-only allowlist makes synthetic demo PDFs available on request; none
are auto-uploaded, processed, or added to run history. Vendor/PO master data
(app.db) starts empty too; nothing auto-loads fabricated records. Load real
(or your own test) vendor/PO data via db.seed_master_data() explicitly.
"""

import json
import logging
import queue
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.guardrails.file_validation import FileValidationError, sanitize_filename, validate_upload
from app.pipeline.run import run_pipeline

# React UI (ui/dist, built via `npm run build`); the legacy vanilla page in
# frontend/ is served only if the build output doesn't exist yet.
_UI_DIST = config.ROOT / "ui" / "dist"
FRONTEND_DIR = _UI_DIST if _UI_DIST.exists() else config.ROOT / "frontend"
STAGE_ORDER = ("extract", "guardrails", "validate", "match", "decide")

_executing: set[int] = set()
_exec_lock = threading.Lock()
_run_queue: queue.Queue[tuple[int, Path] | None] = queue.Queue()
_queue_thread: threading.Thread | None = None
_queue_start_lock = threading.Lock()
log = logging.getLogger("app.api")
STALE_RUN_SECONDS = 180


def _run_queue_worker(run_queue: queue.Queue[tuple[int, Path] | None]) -> None:
    """Drain queued deferred runs; one bad item must not terminate the worker."""
    while True:
        item = run_queue.get()
        try:
            if item is None:
                return
            run_id, pdf_path = item
            run = db.get_run(run_id)
            if not run or run["status"] != "running":
                continue
            with _exec_lock:
                _executing.add(run_id)
            try:
                execute_run(run_id, pdf_path)
            except Exception as exc:
                log.exception("background worker failed for run %s", run_id)
                db.fail_run(run_id, f"Background worker error: {type(exc).__name__}: {exc}")
            finally:
                with _exec_lock:
                    _executing.discard(run_id)
        except Exception:
            # Log unexpected queue infrastructure errors and continue draining.
            log.exception("unhandled background queue error; continuing")
        finally:
            run_queue.task_done()


def _ensure_queue_worker() -> None:
    global _queue_thread
    with _queue_start_lock:
        if _queue_thread is None or not _queue_thread.is_alive():
            _queue_thread = threading.Thread(
                target=_run_queue_worker, args=(_run_queue,),
                name="invoice-run-queue", daemon=True,
            )
            _queue_thread.start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _run_queue
    db.init_db()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stale_count = db.mark_stale_runs(STALE_RUN_SECONDS)
    if stale_count:
        log.warning("marked %d stale invoice run(s) failed at startup", stale_count)
    _run_queue = queue.Queue()
    _ensure_queue_worker()
    try:
        yield
    finally:
        # In normal server operation this runs only on shutdown. It also keeps
        # test clients from leaving queued work behind between isolated DBs.
        _run_queue.join()
        _run_queue.put(None)
        _run_queue.join()
        if _queue_thread:
            _queue_thread.join(timeout=2)


app = FastAPI(title="CentrAlign AI — Invoice Processing Automation", lifespan=lifespan)
from app.worker.router import router as worker_router
app.include_router(worker_router)

# Explicitly downloadable synthetic documents for local evaluation. This is
# an allowlist, not a static mount: examples are never copied, seeded, or run
# automatically, and selecting one still requires the normal upload flow.
EXAMPLE_INVOICES = {
    "INV-8613_meridian.pdf": {
        "description": "Clean text invoice with explicit PO reference (happy path).",
        "expected_decision": "auto_approve when the local vendor/PO fixture data is seeded; otherwise review/reject according to available master data.",
    },
    "INV-0092_vertex_no_po.pdf": {
        "description": "Invoice with no explicit PO reference; exercises fuzzy matching and review routing.",
        "expected_decision": "needs_review with seeded fixture master data.",
    },
    "INV-2026-1099_acme_injection.pdf": {
        "description": "Invoice containing a prompt-injection attempt in free text.",
        "expected_decision": "needs_review; the worker pauses for human review before recording.",
    },
}


@app.get("/api/examples")
def list_example_invoices():
    return {
        "notice": "Synthetic test PDFs only. Downloads are not uploaded, processed, or added to run history automatically.",
        "examples": [
            {"filename": filename, **details, "download_url": f"/api/examples/{filename}"}
            for filename, details in EXAMPLE_INVOICES.items()
        ],
    }


@app.get("/api/examples/{filename}")
def download_example_invoice(filename: str):
    if filename not in EXAMPLE_INVOICES:
        raise HTTPException(404, "Example invoice not found")
    path = config.FIXTURE_INVOICE_DIR / filename
    if not path.is_file():
        raise HTTPException(404, "Example invoice is unavailable")
    return FileResponse(path, media_type="application/pdf", filename=filename)


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

def execute_run(run_id: int, pdf_path: Path) -> dict:
    """Blocking execution (non-deferred API calls). Same path as streaming."""
    final = None
    for event in _execute_events(run_id, pdf_path):
        final = event
    return final


def _execute_events(run_id: int, pdf_path: Path):
    """Run the pipeline for a stored run, yielding events; persists the outcome."""
    final = None
    try:
        prior = db.prior_invoices()
        for event in run_pipeline(pdf_path, prior):
            final = event
            db.append_run_event(run_id, event)
            yield event
        if final and final.get("status") == "completed":
            db.complete_run(run_id, final["result"])
        else:
            db.fail_run(run_id, (final or {}).get("error", "Pipeline produced no result."))
    except Exception as exc:
        log.exception("run execution failed for %s", run_id)
        error = f"{type(exc).__name__}: {exc}"
        failed = {"stage": "pipeline", "status": "failed", "error": error}
        try:
            db.append_run_event(run_id, failed)
        finally:
            db.fail_run(run_id, error)
        yield failed


def _outcome(final: dict | None) -> dict:
    if final and final.get("status") == "completed":
        return {"status": "completed", "result": final["result"]}
    return {"status": "failed", "error": (final or {}).get("error")}


# --------------------------------------------------------------------------
# Run creation (upload only - no bundled/demo data ships in the app)
# --------------------------------------------------------------------------

@app.post("/api/invoices")
async def upload_invoice(file: UploadFile, defer: bool = False):
    content = await file.read()
    # GUARDRAIL 1 (app/guardrails/file_validation.py): reject non-PDF, empty,
    # oversized, or corrupt uploads before a run is even created - the file
    # never reaches extraction.
    try:
        validate_upload(file.filename, content)
    except FileValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

    safe_name = sanitize_filename(file.filename)  # never store/display the raw filename
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stored = config.UPLOAD_DIR / f"{stamp}_{safe_name}"
    stored.write_bytes(content)

    run_id = db.create_run(safe_name, str(stored))
    if defer:
        _ensure_queue_worker()
        _run_queue.put((run_id, stored))
        return {"run_id": run_id, "status": "pending"}
    return {"run_id": run_id, **_outcome(execute_run(run_id, stored))}


# --------------------------------------------------------------------------
# Live run view: SSE stream (executes pending runs, replays finished ones)
# --------------------------------------------------------------------------

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: int):
    db.mark_stale_runs(STALE_RUN_SECONDS)
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id} not found")

    def events():
        # Finished run -> replay its stored trace (reopen from dashboard).
        if run["status"] == "completed" and run["trace"]:
            for name in STAGE_ORDER:
                yield _sse({"stage": name, "status": "completed",
                            "output": run["trace"][name], "replay": True})
            yield _sse({"stage": "pipeline", "status": "completed",
                        "result": run["trace"], "replay": True})
            return
        if run["status"] == "failed":
            stored_events = db.list_run_events(run_id)
            if stored_events:
                for event in stored_events:
                    yield _sse({**event, "replay": True})
            else:
                yield _sse({"stage": "pipeline", "status": "failed",
                            "error": run["error"], "replay": True})
            return

        # The queue worker owns execution. This stream tails durable stage
        # events and therefore remains safe across disconnects/reconnects.
        sequence = -1
        terminal_emitted = False
        while True:
            stored_events = db.list_run_events(run_id, sequence)
            for event in stored_events:
                sequence += 1
                terminal_emitted |= event.get("stage") == "pipeline" and event.get("status") in {"completed", "failed"}
                yield _sse(event)
            latest = db.get_run(run_id)
            if latest is None:
                yield _sse({"stage": "pipeline", "status": "failed", "error": "Run record disappeared."})
                return
            if latest["status"] in {"completed", "failed"}:
                # The client may have been paused after the previous yield
                # while the worker completed. Drain all events committed
                # during that pause before sending any synthetic fallback.
                tail_events = db.list_run_events(run_id, sequence)
                for event in tail_events:
                    sequence += 1
                    terminal_emitted |= event.get("stage") == "pipeline" and event.get("status") in {"completed", "failed"}
                    yield _sse(event)
                if not terminal_emitted:
                    yield _sse({"stage": "pipeline", "status": latest["status"],
                                **({"result": latest["trace"]} if latest["status"] == "completed" else {"error": latest["error"]})})
                return
            db.mark_stale_runs(STALE_RUN_SECONDS)
            time.sleep(0.1)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


# --------------------------------------------------------------------------
# Dashboard reads
# --------------------------------------------------------------------------

@app.get("/api/runs")
def get_runs():
    db.mark_stale_runs(STALE_RUN_SECONDS)
    return db.list_runs()


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    db.mark_stale_runs(STALE_RUN_SECONDS)
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id} not found")
    return run


@app.delete("/api/runs")
def clear_runs():
    return {"deleted": db.delete_all_runs()}


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
