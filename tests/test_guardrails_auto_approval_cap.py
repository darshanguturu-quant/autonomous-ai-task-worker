"""GUARDRAIL 4 - decision-engine bounds: a hard dollar cap on auto-approval.
Even a perfectly clean match (approved vendor, exact PO match, within
tolerance) must never auto-approve above AUTO_APPROVAL_MAX_AMOUNT - it always
routes to Needs Review instead, no exceptions."""

from app.pipeline import decide as decide_mod
from app.pipeline import match as match_mod
from app.pipeline import validate as validate_mod

CAP = decide_mod.AUTO_APPROVAL_MAX_AMOUNT


def _extract_for(vendor: str, po_ref: str, total: float) -> dict:
    f = lambda v: {"value": v, "confidence": 0.95, "source": "test"}
    return {
        "method": "text", "extraction_confidence": 0.95, "num_pages": 1, "text_chars": 900,
        "fields": {
            "vendor_name": f(vendor), "invoice_number": f(f"INV-CAP-{total}"),
            "invoice_date": f("2026-07-19"), "due_date": f("2026-08-18"), "po_ref": f(po_ref),
            "subtotal": f(total), "tax": {"value": None, "confidence": 0.0, "source": "none"},
            "tax_rate": {"value": None, "confidence": 0.0, "source": "none"},
            "total": f(total), "currency": f("USD"),
        },
        "line_items": [{"description": "goods", "qty": 1, "unit_price": total, "amount": total}],
        "warnings": [],
    }


def test_amount_over_cap_forces_needs_review_even_on_a_clean_match():
    # PO-7877 (Northstar) is $54,000 - an exact-amount match, diff 0, well
    # within tolerance. It is also comfortably above the auto-approval cap.
    total = 54000.00
    assert total > CAP
    extract = _extract_for("Northstar Construction Supply Inc.", "PO-7877", total)
    validation = validate_mod.validate(extract)
    m = match_mod.match(extract)
    assert m["amount_check"]["within_tolerance"]  # confirms the match itself is clean

    d = decide_mod.decide(extract, validation, m)
    assert d["decision"] == "needs_review"
    fired = [r["rule"] for r in d["rules_trace"] if r["triggered"]]
    assert fired == ["R8_amount_exceeds_auto_approval_cap"]
    assert f"${CAP:,.2f}" in d["primary_reason"]


def test_amount_under_cap_with_clean_match_still_auto_approves():
    # PO-7852 (Meridian) is $9,168.25 - exact match, well under the cap.
    total = 9168.25
    assert total < CAP
    extract = _extract_for("Meridian IT Services LLC", "PO-7852", total)
    validation = validate_mod.validate(extract)
    m = match_mod.match(extract)

    d = decide_mod.decide(extract, validation, m)
    assert d["decision"] == "auto_approve"
    assert not any(r["triggered"] for r in d["rules_trace"])
