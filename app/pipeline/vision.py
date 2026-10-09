"""Vision-LLM extraction path for scanned / image-only invoice PDFs (Groq).

Groq's vision models take images, not PDFs, so the scanned page is rendered
to a JPEG (pymupdf) and sent through Groq's chat API in JSON mode. The reply
is validated against a Pydantic schema, with one self-correcting retry that
feeds the validation error back to the model. The final result has the exact
same shape the text extractor produces, so Validate/Match/Decide run
unchanged - every field's `source` says it came from vision, and the trace
shows which extraction method ran.
"""

import base64
import json
import logging
import time
from pathlib import Path

import fitz  # pymupdf
from pydantic import BaseModel, ValidationError

from app import config
from app.guardrails.prompt_injection import INJECTION_DEFENSE_NOTE
from app.guardrails.resilience import (
    BACKOFF_BASE_SECONDS,
    IMAGE_TOKENS_FLOOR,
    MAX_COMPLETION_TOKENS,
    PROMPT_TOKENS,
    RATE_LIMIT_RETRIES,
    RENDER_LADDER,
    REQUEST_TOKEN_BUDGET,
    TOKENS_PER_IMAGE_BYTE,
)
from app.pipeline.extract import CRITICAL_FIELDS, ExtractionServiceBusy, VisionNotConfigured

log = logging.getLogger("pipeline.vision")

PROMPT = """You are reading a scanned vendor invoice image. Extract the structured data \
exactly as printed and reply with a single JSON object in this exact shape:

{
  "vendor_name": string|null,
  "invoice_number": string|null,
  "invoice_date": string|null,      // YYYY-MM-DD
  "due_date": string|null,          // YYYY-MM-DD
  "po_ref": string|null,            // purchase-order reference, e.g. "PO-1234"
  "subtotal": number|null,
  "tax": number|null,
  "tax_rate": number|null,          // decimal fraction: 8% -> 0.08; null if no tax line
  "total": number|null,
  "currency": string|null,          // e.g. "USD"
  "line_items": [{"description": string, "qty": integer, "unit_price": number, "amount": number}],
  "field_confidence": {"vendor_name": number, "invoice_number": number, "invoice_date": number,
                       "due_date": number, "po_ref": number, "subtotal": number, "tax": number,
                       "total": number, "currency": number}   // each 0..1, legibility on the scan
}

Rules:
- Use null for anything not printed on the document. Never guess or compute values.
- Amounts are plain numbers without currency symbols or thousands separators.
- """ + INJECTION_DEFENSE_NOTE + """
- Reply with the JSON object only."""


class LineItem(BaseModel):
    description: str
    qty: int
    unit_price: float
    amount: float


class FieldConfidence(BaseModel):
    vendor_name: float
    invoice_number: float
    invoice_date: float
    due_date: float
    po_ref: float
    subtotal: float
    tax: float
    total: float
    currency: float


class VisionExtraction(BaseModel):
    vendor_name: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    po_ref: str | None
    subtotal: float | None
    tax: float | None
    tax_rate: float | None
    total: float | None
    currency: str | None
    line_items: list[LineItem]
    field_confidence: FieldConfidence


# --------------------------------------------------------------------------
# Request-size guardrail (GUARDRAIL 5 - app/guardrails/resilience.py).
#
# Groq's free-tier TPM pre-check (8 000 tokens/min) counts
#     Requested = estimated input tokens + max_completion_tokens
# - measured directly: the same 86 KB image 413s at max_completion_tokens=8192
# (Requested 10931 = ~2739 input estimate + 8192) and succeeds at 4096, with
# actual usage only ~1816 prompt + ~224 completion. So the output allowance,
# not the image, was blowing the budget. The guardrail estimates the full
# request cost BEFORE calling and walks down a dpi/quality render ladder if
# needed; an unexpected 413 falls back to the next smaller render instead of
# surfacing raw to the UI. Constants (MAX_COMPLETION_TOKENS, RENDER_LADDER,
# REQUEST_TOKEN_BUDGET, retry/backoff policy) live in app/guardrails/resilience.py
# so this is policy, not a one-off fix buried in extraction code.
# --------------------------------------------------------------------------


def _completion_with_backoff(client, messages: list, pdf_name: str):
    """Call Groq, retrying 429 rate-limits with exponential backoff (capped).

    413 (request itself too large) is NOT retried here - waiting can't fix an
    oversized request; the caller downscales the image instead.
    """
    from groq import APIStatusError

    delay = BACKOFF_BASE_SECONDS
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return client.chat.completions.create(
                model=config.GROQ_MODEL,
                temperature=0,
                max_completion_tokens=MAX_COMPLETION_TOKENS,  # counted against TPM pre-check
                reasoning_format="hidden",   # qwen thinks before answering; keep JSON clean
                response_format={"type": "json_object"},
                messages=messages,
            )
        except APIStatusError as exc:
            if exc.status_code != 429 or attempt == RATE_LIMIT_RETRIES:
                raise
            retry_after = exc.response.headers.get("retry-after") if exc.response else None
            wait = min(float(retry_after) if retry_after else delay, 60.0)
            log.warning("Groq 429 rate limit on '%s' (attempt %d/%d), retrying in %.1fs: %s",
                        pdf_name, attempt + 1, RATE_LIMIT_RETRIES, wait, exc)
            time.sleep(wait)
            delay *= 2


def _estimate_tokens(jpeg: bytes) -> int:
    image = max(IMAGE_TOKENS_FLOOR, int(len(jpeg) * TOKENS_PER_IMAGE_BYTE))
    return PROMPT_TOKENS + image + MAX_COMPLETION_TOKENS


def _budgeted_renders(pdf_path: Path) -> tuple[list[dict], int]:
    """Render page 1 down the ladder; return every render that fits the budget
    (largest first) so a surprise 413 can fall back to a smaller one.

    Only page 1 is ever sent: invoice header, line items, and totals live
    there, and each extra page would roughly double the request cost. Multi-
    page documents get a visible warning in the trace instead (_to_result)."""
    renders = []
    with fitz.open(pdf_path) as doc:
        num_pages = doc.page_count
        for dpi, quality in RENDER_LADDER:
            # grayscale: invoices are B/W content and it compresses ~30% smaller
            jpeg = doc[0].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY).tobytes(
                "jpeg", jpg_quality=quality)
            est = _estimate_tokens(jpeg)
            if est <= REQUEST_TOKEN_BUDGET:
                renders.append({"jpeg": jpeg, "dpi": dpi, "quality": quality,
                                "kb": len(jpeg) // 1024, "estimated_tokens": est})
    if not renders:
        log.error("'%s' page 1 exceeds the %d-token request budget even at %d dpi",
                  pdf_path.name, REQUEST_TOKEN_BUDGET, RENDER_LADDER[-1][0])
        raise ExtractionServiceBusy(
            "This document is too large for the extraction service even after "
            "compression - try a smaller or lower-resolution PDF."
        )
    return renders, num_pages


def extract_via_vision(pdf_path: Path, text_chars: int) -> dict:
    if not config.GROQ_API_KEY:
        raise VisionNotConfigured(
            f"'{pdf_path.name}' has no usable text layer ({text_chars} chars) and needs "
            "vision extraction, but GROQ_API_KEY is not set. Add it to .env."
        )

    from groq import APIStatusError, Groq  # deferred: text-only runs never need the SDK

    client = Groq(api_key=config.GROQ_API_KEY, timeout=90.0, max_retries=0)
    renders, num_pages = _budgeted_renders(pdf_path)

    last_error = None
    for render in renders:  # first render is the sharpest that fits the estimate
        image_url = ("data:image/jpeg;base64,"
                     + base64.standard_b64encode(render["jpeg"]).decode())
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": PROMPT},
            ],
        }]

        for _ in range(2):  # one self-correcting retry on invalid JSON/schema
            try:
                resp = _completion_with_backoff(client, messages, pdf_path.name)
            except APIStatusError as exc:
                if exc.status_code == 413 and render is not renders[-1]:
                    # estimate was optimistic: downscale and try the next render
                    log.warning("Groq 413 for '%s' at %d dpi, downscaling: %s",
                                pdf_path.name, render["dpi"], exc)
                    last_error = exc
                    break
                if exc.status_code in (413, 429):  # backoff + downscaling both exhausted
                    log.error("Groq rate limit exhausted for '%s': %s", pdf_path.name, exc)
                    raise ExtractionServiceBusy(
                        "Extraction service is temporarily busy - please retry in a minute."
                    ) from exc
                raise
            raw = resp.choices[0].message.content
            try:
                extraction = VisionExtraction.model_validate(json.loads(raw))
                return _to_result(extraction, text_chars, num_pages, render)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                messages += [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content":
                        f"That JSON did not match the required schema: {exc}. "
                        "Reply again with a single corrected JSON object only."},
                ]
        else:
            # GUARDRAIL 3 - LLM OUTPUT VALIDATION: the model returned output
            # that failed Pydantic validation twice (once self-corrected).
            # That is a validation failure, not a crash - degrade to a
            # zero-confidence result so Validate/Decide route this to Needs
            # Review ("extraction confidence low"), never a raw 500.
            log.error("vision extraction of '%s' returned invalid JSON twice (%s): %s",
                      pdf_path.name, config.GROQ_MODEL, last_error)
            return _degraded_result(
                text_chars, num_pages,
                "model output did not match the required schema after a self-correcting retry",
            )
    # Unreachable in practice (the last render raises rather than breaking),
    # but kept so an exhausted loop can never fall through silently.
    log.error("vision extraction of '%s' failed on every render: %s", pdf_path.name, last_error)
    raise ExtractionServiceBusy(
        "Extraction service could not process this document - please retry in a minute."
    )


def _degraded_result(text_chars: int, num_pages: int, reason: str) -> dict:
    """Same result shape as a successful extraction, but every field is
    zero-confidence and unset. extraction_confidence=0.0 trips R5 (low
    extraction confidence) and every required-field check in Validate trips
    R2 - both route to Needs Review, so a bad LLM response degrades the run
    instead of crashing it."""
    def missing(name: str) -> dict:
        return {"value": None, "confidence": 0.0, "source": f"vision: {reason}"}

    names = ("vendor_name", "invoice_number", "invoice_date", "due_date", "po_ref",
             "subtotal", "tax", "tax_rate", "total", "currency")
    return {
        "method": "vision",
        "model": config.GROQ_MODEL,
        "extraction_confidence": 0.0,
        "num_pages": num_pages,
        "text_chars": text_chars,
        "fields": {name: missing(name) for name in names},
        "line_items": [],
        "warnings": [f"extraction confidence low: {reason}"],
    }


def _to_result(ex: VisionExtraction, text_chars: int, num_pages: int, render: dict) -> dict:
    conf = ex.field_confidence

    def field(name: str, value):
        if value is None:
            return {"value": None, "confidence": 0.0, "source": "vision: not found on document"}
        c = round(min(max(getattr(conf, name, 0.0), 0.0), 1.0), 2)
        return {"value": value, "confidence": c, "source": "vision: model-reported confidence"}

    fields = {
        "vendor_name": field("vendor_name", ex.vendor_name),
        "invoice_number": field("invoice_number", ex.invoice_number),
        "invoice_date": field("invoice_date", ex.invoice_date),
        "due_date": field("due_date", ex.due_date),
        "po_ref": field("po_ref", ex.po_ref),
        "subtotal": field("subtotal", ex.subtotal),
        "tax": field("tax", ex.tax),
        "tax_rate": {
            "value": ex.tax_rate,
            "confidence": field("tax", ex.tax)["confidence"] if ex.tax_rate is not None else 0.0,
            "source": "vision: model-reported confidence" if ex.tax_rate is not None
                      else "vision: no tax line on document",
        },
        "total": field("total", ex.total),
        "currency": field("currency", ex.currency),
    }

    warnings = [f"field '{name}' not found on scanned document"
                for name in CRITICAL_FIELDS if fields[name]["value"] is None]
    if num_pages > 1:
        warnings.append(
            f"document has {num_pages} pages; only page 1 was sent to vision "
            "extraction (keeps the request inside the API token budget)"
        )
    confidence = round(
        sum(fields[n]["confidence"] for n in CRITICAL_FIELDS) / len(CRITICAL_FIELDS), 2
    )

    return {
        "method": "vision",
        "model": config.GROQ_MODEL,
        "image_sent": {"dpi": render["dpi"], "jpeg_quality": render["quality"],
                       "size_kb": render["kb"],
                       "estimated_request_tokens": render["estimated_tokens"]},
        "extraction_confidence": confidence,
        "num_pages": num_pages,
        "text_chars": text_chars,
        "fields": fields,
        "line_items": [li.model_dump() for li in ex.line_items],
        "warnings": warnings,
    }
