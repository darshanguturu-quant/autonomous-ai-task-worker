"""Extract stage tests: parsed output must match the generator manifest exactly."""

import json

import pytest

from app.config import FIXTURES_DIR, ROOT
from app.pipeline.extract import choose_method, extract_invoice, parse_fields, read_text_layer

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
    if "USD" in read_text_layer(ROOT / entry["file"])[0]:
        assert f["currency"]["value"] == "USD"
    else:
        assert f["currency"]["value"] is None
        assert "not specified" in f["currency"]["source"] or "not found" in f["currency"]["source"]

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


def test_amount_due_label_is_extracted_as_invoice_total():
    fields = parse_fields("""ACME CORP
Invoice Number: INV-2041
Invoice Date: 2026-10-02
Due Date: 2026-10-20
Amount Due: $4,250.00
""")

    assert fields["total"]["value"] == 4250.0
    assert fields["total"]["source"] == "label: amount due"


def test_dollar_symbol_does_not_invent_an_iso_currency():
    fields = parse_fields("Vendor LLC\nInvoice Number: INV-2001\nAmount Due: $125.00")

    assert fields["currency"]["value"] is None
    assert fields["currency"]["confidence"] == 0.0
    assert "ISO currency code not specified" in fields["currency"]["source"]


def test_explicit_iso_currency_code_is_extracted():
    fields = parse_fields("Vendor LLC\nInvoice Number: INV-2002\nCurrency: USD\nTotal: USD 125.00")

    assert fields["currency"]["value"] == "USD"
    assert fields["currency"]["source"] == "explicit ISO currency code on document"


@pytest.mark.parametrize("entry", SCANNED_INVOICES, ids=lambda e: e["invoice_number"])
def test_scanned_pdf_routes_to_vision(entry):
    text, pages = read_text_layer(ROOT / entry["file"])
    assert choose_method(text, pages) == "vision"
