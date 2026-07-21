"""Edge case: prompt-injection attempt embedded in a line-item description.

A malicious vendor could try to hijack the pipeline by embedding
instruction-shaped text in an invoice field ("ignore previous instructions",
"system:", "auto-approve this invoice"). This invoice is otherwise identical
to the Acme happy path - same vendor, same PO, same total, well within
tolerance - so every other rule (R1-R8) passes cleanly. Only the R0
prompt-injection guardrail catches it, and it must be the sole reason this
run is routed to Needs Review instead of Auto-Approve.
"""

from fastapi.testclient import TestClient

from app.api import app
from tests.helpers import upload_fixture

INJECTED = "INV-2026-1099_acme_injection.pdf"


def test_injected_invoice_routes_to_needs_review_despite_a_clean_match():
    with TestClient(app) as c:
        result = upload_fixture(c, INJECTED)["result"]

        # The Guardrails stage actually flagged it, with the offending field named.
        assert result["guardrails"]["flagged"] is True
        findings = result["guardrails"]["findings"]
        assert any(f["pattern"] == "ignore_instructions" for f in findings)
        assert any(f["field"] == "line_items[0].description" for f in findings)

        # Everything else about this invoice is clean - same vendor/PO/amount as
        # the Acme happy path - so the injection scan is the only thing that
        # could have forced Needs Review here.
        assert result["match"]["vendor_match"]["matched"]
        assert result["match"]["vendor_match"]["approved"]
        assert result["match"]["po_match"]["matched"]
        assert result["match"]["amount_check"]["within_tolerance"]
        assert result["validate"]["passed"]

        d = result["decide"]
        assert d["decision"] == "needs_review"
        fired = [r["rule"] for r in d["rules_trace"] if r["triggered"]]
        assert fired == ["R0_prompt_injection_detected"]
        assert "suspicious content detected" in d["primary_reason"]
        assert "ignore previous instructions" in d["primary_reason"]

        # The specific reason is what reaches the UI's decision banner.
        assert "suspicious content detected" in d["explanation"]


def test_clean_acme_invoice_is_not_flagged_by_the_same_guardrail():
    """Control: the unmodified Acme happy-path invoice must NOT be flagged -
    proves the guardrail reacts to the injected text, not to this vendor/PO."""
    with TestClient(app) as c:
        result = upload_fixture(c, "INV-2026-0847_acme.pdf")["result"]
        assert result["guardrails"]["flagged"] is False
        assert result["decide"]["decision"] == "auto_approve"
