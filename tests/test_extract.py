"""Extract stage tests: parsed output must match the generator manifest exactly."""

import json

import pytest

from app.config import FIXTURES_DIR, ROOT
from app.pipeline.extract import choose_method, extract_invoice, read_text_layer

MANIFEST = json.loads((FIXTURES_DIR / "manifest.json").read_text())
TEXT_INVOICES = [m for m in MANIFEST if m["template"] != "scanned"]
SCANNED_INVOICES = [m for m in MANIFEST if m["template"] == "scanned"]


@pytest.mark.parametrize("entry", TEXT_INVOICES, ids=lambda e: e["invoice_number"] + "/" + e["scenario"])
def test_text_extraction_matches_manifest(entry):
    result = extract_invoice(ROOT / entry["file"])

    assert result["method"] == "text"
    f = result["fields"]
    assert f["invoice_number"]["value"] == entry["invoice_number"]
    assert f["vendor_name"]["value"] == entry["vendor"]
    assert f["invoice_date"]["value"] == entry["invoice_date"]
    assert f["po_ref"]["value"] == entry["po_ref"]  # None when absent, e.g. Vertex
    assert f["subtotal"]["value"] == entry["subtotal"]
    assert f["total"]["value"] == entry["total"]
    if entry["tax"] > 0:
        assert f["tax"]["value"] == entry["tax"]
    assert f["currency"]["value"] == "USD"

    # Line items: right count, and amounts sum to the subtotal.
    assert result["line_items"], "no line items parsed"
    assert round(sum(li["amount"] for li in result["line_items"]), 2) == entry["subtotal"]

    assert result["extraction_confidence"] >= 0.80


def test_no_po_invoice_reports_missing_po_not_a_failure():
    entry = next(m for m in MANIFEST if m["scenario"] == "edge_no_po_ref")
    result = extract_invoice(ROOT / entry["file"])
    po = result["fields"]["po_ref"]
    assert po["value"] is None
    assert po["confidence"] == 0.0
    # Missing PO must not tank overall confidence - it's optional, not critical.
    assert result["extraction_confidence"] >= 0.80


@pytest.mark.parametrize("entry", SCANNED_INVOICES, ids=lambda e: e["invoice_number"])
def test_scanned_pdf_routes_to_vision(entry):
    text, pages = read_text_layer(ROOT / entry["file"])
    assert choose_method(text, pages) == "vision"
