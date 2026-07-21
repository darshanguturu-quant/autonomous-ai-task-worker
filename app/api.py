"""FastAPI backend: upload/run invoices, live SSE streaming, run history.

Endpoints:
  POST /api/invoices              upload a PDF; ?defer=1 -> create run only,
                                  execution happens on the SSE stream
  GET  /api/runs/{id}/stream      SSE: executes the pipeline live, one event per
                                  stage; finished runs are replayed (replay=true)
  GET  /api/runs                  run history (dashboard)
  GET  /api/runs/{id}             one run incl. full per-stage trace
  DELETE /api/runs                clear history (demo reset)
The static frontend is served at /.

Upload is the only way to feed a PDF into this app - there is no bundled
sample/demo data baked into the running product. The vendor/PO master data
(app.db) starts empty too; nothing here auto-loads fabricated content. Load
real (or your own test) vendor/PO data via db.seed_master_data() explicitly.
"""

import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Invoice Processing Automation", lifespan=lifespan)


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
    prior = db.prior_invoices()
    final = None
    try:
        for event in run_pipeline(pdf_path, prior):
            final = event
            yield event
    finally:
        if final and final.get("status") == "completed":
            db.complete_run(run_id, final["result"])
        else:
            db.fail_run(run_id, (final or {}).get("error", "pipeline produced no result"))


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
        return {"run_id": run_id, "status": "pending"}
    return {"run_id": run_id, **_outcome(execute_run(run_id, stored))}


# --------------------------------------------------------------------------
# Live run view: SSE stream (executes pending runs, replays finished ones)
# --------------------------------------------------------------------------

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: int):
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id} not found")

    def events():
        # Finished run -> replay the stored trace (reopen from dashboard).
        if run["status"] == "completed" and run["trace"]:
            for name in STAGE_ORDER:
                yield _sse({"stage": name, "status": "completed",
                            "output": run["trace"][name], "replay": True})
            yield _sse({"stage": "pipeline", "status": "completed",
                        "result": run["trace"], "replay": True})
            return
        if run["status"] == "failed":
            yield _sse({"stage": "pipeline", "status": "failed",
                        "error": run["error"], "replay": True})
            return

        # Pending run -> execute NOW, streaming each stage as it happens.
        with _exec_lock:
            if run_id in _executing:
                yield _sse({"stage": "pipeline", "status": "failed",
                            "error": "run is already executing in another stream"})
                return
            _executing.add(run_id)
        try:
            for event in _execute_events(run_id, Path(run["stored_path"])):
                yield _sse(event)
        finally:
            with _exec_lock:
                _executing.discard(run_id)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


# --------------------------------------------------------------------------
# Dashboard reads
# --------------------------------------------------------------------------

@app.get("/api/runs")
def get_runs():
    return db.list_runs()


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id} not found")
    return run


@app.delete("/api/runs")
def clear_runs():
    return {"deleted": db.delete_all_runs()}


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
