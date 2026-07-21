"""Edge case: split PO - one PO (PO-7877, $54,000), three progress billings.

A naive per-invoice amount check fails in BOTH directions here:
  - it would flag invoice 1 ($18,000 vs $54,000 PO) as a huge mismatch, and
  - it would pass invoice 3 ($20,000 vs $54,000 PO) even though it over-runs
    the PO cumulatively.
The cumulative billed-to-date check gets both right.
"""

from fastapi.testclient import TestClient

from app.api import app
from tests.helpers import upload_fixture

P1, P2, P3 = ("INV-2026-0912_northstar_p1.pdf",
              "INV-2026-0933_northstar_p2.pdf",
              "INV-2026-0958_northstar_p3.pdf")


def _run(client, name):
    return upload_fixture(client, name)["result"]


def test_split_po_cumulative_sequence():
    with TestClient(app) as c:
        r1 = _run(c, P1)
        a1 = r1["match"]["amount_check"]
        assert a1["billing_mode"] == "partial"
        assert a1["cumulative_prior"] == 0 and a1["cumulative_with_this_invoice"] == 18000.00
        assert r1["decide"]["decision"] == "auto_approve"
        assert "partial billing" in r1["decide"]["explanation"]

        r2 = _run(c, P2)
        a2 = r2["match"]["amount_check"]
        assert a2["cumulative_prior"] == 18000.00
        assert a2["cumulative_with_this_invoice"] == 36000.00
        assert a2["cumulative_within_po"]
        assert r2["decide"]["decision"] == "auto_approve"

        r3 = _run(c, P3)
        a3 = r3["match"]["amount_check"]
        assert a3["cumulative_prior"] == 36000.00
        assert a3["cumulative_with_this_invoice"] == 56000.00
        assert not a3["cumulative_within_po"]  # 56,000 > 54,000 + 1,080 tolerance
        assert r3["decide"]["decision"] == "needs_review"
        fired = [r["rule"] for r in r3["decide"]["rules_trace"] if r["triggered"]]
        assert fired == ["R7_cumulative_exceeds_po"]
        assert "$56,000.00" in r3["decide"]["primary_reason"]


def test_naive_per_invoice_check_would_be_wrong_both_ways():
    with TestClient(app) as c:
        # Invoice 1: way off the PO total per-invoice, yet correctly approved.
        r1 = _run(c, P1)
        assert not r1["match"]["amount_check"]["within_tolerance"]
        assert r1["decide"]["decision"] == "auto_approve"

        _run(c, P2)

        # Invoice 3: also just a partial amount per-invoice, but cumulative
        # overrun -> correctly flagged for review.
        r3 = _run(c, P3)
        assert r3["decide"]["decision"] == "needs_review"


def test_rejected_runs_do_not_count_toward_cumulative():
    with TestClient(app) as c:
        _run(c, P1)
        dup = _run(c, P1)  # same invoice again -> duplicate reject
        assert dup["decide"]["decision"] == "reject"
        r2 = _run(c, P2)
        # the rejected duplicate must NOT inflate billed-to-date
        assert r2["match"]["amount_check"]["cumulative_prior"] == 18000.00
        assert r2["decide"]["decision"] == "auto_approve"
