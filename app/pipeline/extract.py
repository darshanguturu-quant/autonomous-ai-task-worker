"""Stage 1 - EXTRACT: invoice PDF -> structured fields with per-field confidence.

Text-native PDFs are parsed directly (pymupdf + label-based regexes).
Image-only / low-text PDFs are routed to the vision-LLM path (app.pipeline.vision).

Every field carries {value, confidence, source} so the run view and the
decision trace can show exactly where each number came from.
"""

import re
from pathlib import Path

import fitz  # pymupdf

# Below this many extractable characters per page the PDF is treated as a
# scan and routed to vision extraction.
MIN_TEXT_CHARS_PER_PAGE = 100

MONEY = r"\$?([\d,]+\.\d{2})"


class VisionNotConfigured(Exception):
    """Raised when a scanned PDF needs vision extraction but no API key is set."""


class ExtractionServiceBusy(Exception):
    """Vision service rate-limited/unavailable after retries. The message is
    user-facing (shown in the UI), so it must stay non-technical - full API
    detail is logged server-side instead."""


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def _field(value, confidence: float, source: str) -> dict:
    return {"value": value, "confidence": round(confidence, 2), "source": source}


def _missing(source: str = "not found") -> dict:
    return {"value": None, "confidence": 0.0, "source": source}


def read_text_layer(pdf_path: str | Path) -> tuple[str, int]:
    """Return (full text, page count) from the PDF's embedded text layer."""
    with fitz.open(pdf_path) as doc:
        text = "\n".join(page.get_text() for page in doc)
        return text, doc.page_count


def choose_method(text: str, num_pages: int) -> str:
    """'text' if the PDF has a usable text layer, else 'vision'."""
    return "text" if len(text.strip()) >= MIN_TEXT_CHARS_PER_PAGE * max(num_pages, 1) else "vision"


# --------------------------------------------------------------------------
# Field parsers (label-based; \s in patterns spans newlines, which covers
# layouts that put the label and value on separate lines)
# --------------------------------------------------------------------------

def _search(text: str, patterns: list[str]) -> re.Match | None:
    for pat in patterns:
        if m := re.search(pat, text, re.IGNORECASE):
            return m
    return None


def parse_fields(text: str) -> dict[str, dict]:
    fields: dict[str, dict] = {}
    lines = [ln.strip() for ln in text.splitlines()]

    # Vendor: no label on real invoices - heuristic, first non-empty line.
    vendor = next((ln for ln in lines if ln), None)
    fields["vendor_name"] = (
        _field(vendor, 0.70, "heuristic: first line of document") if vendor else _missing()
    )

    m = _search(text, [r"invoice\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,})"])
    fields["invoice_number"] = (
        _field(m.group(1), 0.95, "label: invoice number") if m else _missing()
    )

    date_pat = r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"
    m = _search(text, [rf"invoice date\s*:?\s*{date_pat}", rf"\bdate\s*:?\s*{date_pat}"])
    fields["invoice_date"] = _field(m.group(1), 0.95, "label: invoice date") if m else _missing()

    m = _search(text, [rf"due(?:\s*date)?\s*:?\s*{date_pat}"])
    fields["due_date"] = _field(m.group(1), 0.90, "label: due date") if m else _missing()

    m = _search(text, [r"(?:po number|purchase order|po ref|po no\.?|po\s*#)\s*:?\s*(PO[-\s]?\d+)"])
    fields["po_ref"] = (
        _field(m.group(1).replace(" ", "-").upper(), 0.95, "label: PO reference")
        if m
        else _missing("no PO reference on document")
    )

    m = _search(text, [rf"subtotal\s*:?\s*(?:USD\s*)?{MONEY}"])
    fields["subtotal"] = _field(_money(m.group(1)), 0.95, "label: subtotal") if m else _missing()

    m = _search(text, [rf"tax\s*\(?([\d.]+)%\)?\s*:?\s*{MONEY}"])
    if m:
        fields["tax"] = _field(_money(m.group(2)), 0.95, f"label: tax ({m.group(1)}%)")
        fields["tax_rate"] = _field(float(m.group(1)) / 100, 0.95, "label: tax rate")
    else:
        fields["tax"] = _missing("no tax line on document")
        fields["tax_rate"] = _missing("no tax line on document")

    # (?<![A-Za-z]) keeps this from matching the tail of "Subtotal".
    m = _search(text, [
        rf"(?<![A-Za-z])total\s*(?:due)?\s*\(?(?:USD)?\)?\s*:?\s*(?:USD\s*)?{MONEY}",
        rf"amount\s+due\s*:?\s*(?:USD\s*)?{MONEY}",
    ])
    fields["total"] = (
        _field(_money(m.group(1)), 0.95, "label: amount due" if "amount" in m.group(0).lower() else "label: total due")
        if m else _missing()
    )

    currency_match = _search(text, [
        r"\b(USD|CAD|AUD|NZD|EUR|GBP|JPY|CNY|INR|CHF|SGD|HKD|MXN|BRL|ZAR)\b"
    ])
    if currency_match:
        fields["currency"] = _field(
            currency_match.group(1).upper(), 0.95, "explicit ISO currency code on document"
        )
    elif "$" in text:
        fields["currency"] = _missing("dollar symbol present; ISO currency code not specified")
    else:
        fields["currency"] = _missing("no currency code or symbol found")
    return fields


# --------------------------------------------------------------------------
# Line items - two strategies, keep whichever finds more rows:
#   columnar: "desc   qty   unit   amount" on one line (monospace layouts)
#   vertical: desc/qty/unit/amount on 4 consecutive lines (drawn-table layouts)
# --------------------------------------------------------------------------

_COLUMNAR = re.compile(rf"^(.{{3,}}?)\s{{2,}}(\d+)\s+{MONEY}\s+{MONEY}\s*$")


def _columnar_items(lines: list[str]) -> list[dict]:
    items = []
    for ln in lines:
        if m := _COLUMNAR.match(ln):
            items.append({
                "description": m.group(1).strip(),
                "qty": int(m.group(2)),
                "unit_price": _money(m.group(3)),
                "amount": _money(m.group(4)),
            })
    return items


def _vertical_items(lines: list[str]) -> list[dict]:
    items = []
    i = 0
    while i + 3 < len(lines):
        desc, qty, unit, amount = lines[i : i + 4]
        if (
            desc
            and not re.fullmatch(r"[\d,.]+", desc)
            and re.fullmatch(r"\d+", qty)
            and re.fullmatch(r"[\d,]+\.\d{2}", unit)
            and re.fullmatch(r"[\d,]+\.\d{2}", amount)
        ):
            items.append({
                "description": desc,
                "qty": int(qty),
                "unit_price": _money(unit),
                "amount": _money(amount),
            })
            i += 4
        else:
            i += 1
    return items


def parse_line_items(text: str) -> list[dict]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    columnar, vertical = _columnar_items(lines), _vertical_items(lines)
    return columnar if len(columnar) >= len(vertical) else vertical


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------

CRITICAL_FIELDS = ("vendor_name", "invoice_number", "invoice_date", "total")


def extract_invoice(pdf_path: str | Path) -> dict:
    """Extract structured data from an invoice PDF.

    Returns a dict with method, per-field values/confidence, line items,
    an overall extraction confidence, and any warnings.
    """
    pdf_path = Path(pdf_path)
    text, num_pages = read_text_layer(pdf_path)
    chars = len(text.strip())
    threshold = MIN_TEXT_CHARS_PER_PAGE * max(num_pages, 1)
    method = choose_method(text, num_pages)

    if method == "vision":
        from app.pipeline import vision  # late import: only needed for scans

        result = vision.extract_via_vision(pdf_path, text_chars=chars)
        result["routing"] = (
            f"text layer has {chars} extractable chars (< {threshold} needed for "
            f"{num_pages} page(s)) -> image-only/scanned PDF -> vision-LLM extraction"
        )
        return result

    fields = parse_fields(text)
    line_items = parse_line_items(text)

    warnings = [
        f"field '{name}' {f['source']}"
        for name, f in fields.items()
        if f["value"] is None and name in CRITICAL_FIELDS
    ]
    if not line_items:
        warnings.append("no line items parsed from document")

    confidence = round(
        sum(fields[name]["confidence"] for name in CRITICAL_FIELDS) / len(CRITICAL_FIELDS), 2
    )

    return {
        "method": "text",
        "routing": (
            f"text layer has {chars} extractable chars (>= {threshold}) "
            "-> text-native parse, no LLM call"
        ),
        "extraction_confidence": confidence,
        "num_pages": num_pages,
        "text_chars": chars,
        "fields": fields,
        "line_items": line_items,
        "warnings": warnings,
    }
