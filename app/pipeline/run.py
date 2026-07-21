"""Pipeline orchestrator: Extract -> Guardrails -> Validate -> Match -> Decide.

The Guardrails stage (app/pipeline/guardrails.py) screens every extracted
field for prompt-injection attempts before Validate/Match/Decide ever see the
data - see app/guardrails/ for the full guardrails layer (file validation,
injection detection, output bounds, resilience).

`run_pipeline` is a generator that yields one event per stage as it actually
executes - the SSE endpoint streams these to the live run view, and tests
consume the same events. Nothing in the UI is simulated: an event exists only
because the stage function really ran, and completed events carry the
measured duration of that execution.

Event shape:
  {"stage": <name>, "status": "running"}
  {"stage": <name>, "status": "completed", "output": {...}, "duration_ms": int}
  {"stage": "pipeline", "status": "failed", "error": "..."}       on error
  {"stage": "pipeline", "status": "completed", "result": {...}, "total_duration_ms": int}
"""

import logging
import time
from collections.abc import Iterator
from pathlib import Path

from app.pipeline import decide as decide_mod
from app.pipeline import guardrails as guardrails_mod
from app.pipeline import match as match_mod
from app.pipeline import validate as validate_mod
from app.pipeline.extract import ExtractionServiceBusy, VisionNotConfigured, extract_invoice

log = logging.getLogger("pipeline")


def public_error(exc: Exception) -> str:
    """User-facing error text for a failed run.

    Raw Groq exceptions carry the org ID, model name, and billing URLs - those
    must never reach the UI. Our own exception types carry deliberately clean
    messages and pass through as-is; anything from the Groq SDK collapses to a
    generic 'busy' line. The full exception is always logged by the caller.
    """
    if isinstance(exc, (ExtractionServiceBusy, VisionNotConfigured)):
        return str(exc)
    try:
        from groq import GroqError
        if isinstance(exc, GroqError):
            return "Extraction service is temporarily busy - please retry in a minute."
    except ImportError:
        pass
    return f"{type(exc).__name__}: {exc}"


def invoice_summary(extract_result: dict) -> dict:
    """Flat summary of an extracted invoice (for storage and duplicate checks)."""
    f = extract_result["fields"]
    return {
        "invoice_number": f["invoice_number"]["value"],
        "vendor_name": f["vendor_name"]["value"],
        "invoice_date": f["invoice_date"]["value"],
        "po_ref": f["po_ref"]["value"],
        "total": f["total"]["value"],
    }


def run_pipeline(pdf_path: str | Path, prior_invoices: list[dict] | None = None) -> Iterator[dict]:
    prior_invoices = prior_invoices or []
    out: dict = {}

    stages = [
        ("extract", lambda: extract_invoice(pdf_path)),
        ("guardrails", lambda: guardrails_mod.screen(out["extract"])),
        ("validate", lambda: validate_mod.validate(out["extract"])),
        ("match", lambda: match_mod.match(out["extract"], prior_invoices)),
        ("decide", lambda: decide_mod.decide(out["extract"], out["validate"], out["match"],
                                             prior_invoices, out["guardrails"])),
    ]

    t_start = time.perf_counter()
    try:
        for name, fn in stages:
            yield {"stage": name, "status": "running"}
            t0 = time.perf_counter()
            out[name] = fn()
            yield {
                "stage": name,
                "status": "completed",
                "output": out[name],
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }

        yield {
            "stage": "pipeline",
            "status": "completed",
            "total_duration_ms": int((time.perf_counter() - t_start) * 1000),
            "result": {
                "invoice": invoice_summary(out["extract"]),
                "extract": out["extract"],
                "guardrails": out["guardrails"],
                "validate": out["validate"],
                "match": out["match"],
                "decide": out["decide"],
            },
        }
    except Exception as exc:  # surfaced to the run view as a failed run
        # Full detail (traceback, raw API body) goes to the server console only;
        # the UI and the stored run get the sanitized message.
        log.exception("pipeline failed for %s", pdf_path)
        yield {"stage": "pipeline", "status": "failed", "error": public_error(exc)}


def run_pipeline_collect(pdf_path: str | Path, prior_invoices: list[dict] | None = None) -> dict:
    """Run to completion and return the final event (convenience for tests/CLI)."""
    final = None
    for event in run_pipeline(pdf_path, prior_invoices):
        final = event
    return final
