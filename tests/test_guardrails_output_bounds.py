"""GUARDRAIL 3 - LLM/extraction output validation: numeric sanity bounds
never let a negative or absurdly large amount reach Auto-Approve."""

from app.guardrails.output_bounds import check_amount_bounds
from app.pipeline import validate as validate_mod


def _extract_stub(total: float, subtotal: float | None = None) -> dict:
    f = lambda v: {"value": v, "confidence": 0.95, "source": "test"}
    subtotal = total if subtotal is None else subtotal
    return {
        "method": "text", "extraction_confidence": 0.9, "num_pages": 1, "text_chars": 500,
        "fields": {
            "vendor_name": f("Acme Office Supplies Ltd."), "invoice_number": f("INV-TEST-9"),
            "invoice_date": f("2026-07-19"), "due_date": f("2026-08-18"),
            "po_ref": f("PO-7841"), "subtotal": f(subtotal),
            "tax": {"value": None, "confidence": 0.0, "source": "none"},
            "tax_rate": {"value": None, "confidence": 0.0, "source": "none"},
            "total": f(total), "currency": f("USD"),
        },
        "line_items": [{"description": "test", "qty": 1, "unit_price": total, "amount": total}],
        "warnings": [],
    }


def test_negative_total_flagged():
    issues = check_amount_bounds(_extract_stub(-500.0)["fields"])
    assert any(i["field"] == "total" for i in issues)


def test_absurdly_large_total_flagged():
    issues = check_amount_bounds(_extract_stub(1_500_000_000.0)["fields"])  # $1.5B
    assert any(i["field"] == "total" for i in issues)


def test_normal_amount_not_flagged():
    assert check_amount_bounds(_extract_stub(2527.20)["fields"]) == []


def test_missing_amount_not_flagged():
    fields = _extract_stub(100.0)["fields"]
    fields["total"] = {"value": None, "confidence": 0.0, "source": "not found"}
    assert check_amount_bounds(fields) == []


def test_absurd_total_fails_validation_and_never_auto_approves():
    """A $1B office-supplies invoice must fail Validate, not sail through."""
    extract = _extract_stub(1_000_000_000.0, subtotal=925_925_925.93)
    validation = validate_mod.validate(extract)
    assert not validation["passed"]
    failed = [c["name"] for c in validation["checks"] if not c["passed"]]
    assert "amount_sanity_bounds" in failed


def test_negative_total_fails_validation():
    extract = _extract_stub(-100.0, subtotal=-100.0)
    validation = validate_mod.validate(extract)
    assert not validation["passed"]
    failed = [c["name"] for c in validation["checks"] if not c["passed"]]
    assert "amount_sanity_bounds" in failed
