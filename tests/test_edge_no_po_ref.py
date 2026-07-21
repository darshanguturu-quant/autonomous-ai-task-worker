"""Edge case: missing PO reference + amount beyond tolerance.

The Vertex invoice has no PO number. The system must NOT stop at "no match
found": it fuzzy-matches by vendor + closest amount, names the candidate PO,
quantifies the discrepancy against the tolerance, and routes to Needs Review.
"""

from fastapi.testclient import TestClient

from app.api import app
from app.pipeline import decide as decide_mod
from app.pipeline import match as match_mod
from tests.helpers import upload_fixture

VERTEX = "INV-0092_vertex_no_po.pdf"


def test_no_po_ref_routes_to_needs_review_with_named_candidate():
    with TestClient(app) as c:
        result = upload_fixture(c, VERTEX)["result"]

        # extraction honestly reports the missing PO
        assert result["extract"]["fields"]["po_ref"]["value"] is None

        po = result["match"]["po_match"]
        assert po["matched"] and po["match_type"] == "fuzzy_vendor_amount"
        assert po["po_number"] == "PO-7869"
        assert "PO-7869" in po["candidates_considered"]

        amount = result["match"]["amount_check"]
        assert amount["po_amount"] == 5200.00 and amount["invoice_total"] == 5750.50
        assert amount["difference"] == 550.50
        assert amount["tolerance"] == 104.00  # max(2% of 5,200, $50)
        assert not amount["within_tolerance"]

        d = result["decide"]
        assert d["decision"] == "needs_review"
        assert [r["rule"] for r in d["rules_trace"] if r["triggered"]][0] == \
            "R6_fuzzy_po_needs_confirmation"
        # the explanation names the candidate and the specific discrepancy
        for needle in ("PO-7869", "$550.50", "$104.00", "$5,200.00", "$5,750.50"):
            assert needle in d["explanation"], f"explanation missing {needle}"


def _vertex_extract_stub(total: float) -> dict:
    """Synthetic extract result: Vertex invoice, no PO ref, given total."""
    f = lambda v: {"value": v, "confidence": 0.95, "source": "test"}
    return {
        "method": "text", "extraction_confidence": 0.9, "num_pages": 1, "text_chars": 500,
        "fields": {
            "vendor_name": f("Vertex Marketing Group"),
            "invoice_number": f("INV-TEST-1"), "invoice_date": f("2026-07-16"),
            "due_date": f("2026-08-15"), "po_ref": {"value": None, "confidence": 0.0,
                                                    "source": "no PO reference on document"},
            "subtotal": f(total), "tax": {"value": None, "confidence": 0.0, "source": "none"},
            "tax_rate": {"value": None, "confidence": 0.0, "source": "none"},
            "total": f(total), "currency": f("USD"),
        },
        "line_items": [{"description": "svc", "qty": 1, "unit_price": total, "amount": total}],
        "warnings": [],
    }


def test_fuzzy_match_within_tolerance_still_needs_human_confirmation():
    """Policy rule R6: a guessed PO is never auto-paid, even when the amount fits."""
    from app.pipeline import validate as validate_mod

    extract = _vertex_extract_stub(total=5200.00)  # exactly the PO amount
    validation = validate_mod.validate(extract)
    m = match_mod.match(extract)
    assert m["po_match"]["match_type"] == "fuzzy_vendor_amount"
    assert m["amount_check"]["within_tolerance"]

    d = decide_mod.decide(extract, validation, m)
    assert d["decision"] == "needs_review"
    fired = [r["rule"] for r in d["rules_trace"] if r["triggered"]]
    assert fired == ["R6_fuzzy_po_needs_confirmation"]
