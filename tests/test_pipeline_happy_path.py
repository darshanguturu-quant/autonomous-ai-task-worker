"""Happy-path tests for Validate -> Match -> Decide on the two clean invoices."""

from app.config import FIXTURE_INVOICE_DIR
from app.pipeline.run import run_pipeline, run_pipeline_collect

ACME = FIXTURE_INVOICE_DIR / "INV-2026-0847_acme.pdf"    # $2,527.20 vs PO $2,500 (within $50)
MERIDIAN = FIXTURE_INVOICE_DIR / "INV-8613_meridian.pdf"  # exact PO amount match


def test_all_five_stages_emit_real_events():
    events = list(run_pipeline(ACME))
    completed = [e["stage"] for e in events if e["status"] == "completed"]
    assert completed == ["extract", "guardrails", "validate", "match", "decide", "pipeline"]
    # every completed stage carries real intermediate output
    assert all("output" in e for e in events if e["status"] == "completed" and e["stage"] != "pipeline")


def test_acme_happy_path_auto_approves_within_tolerance():
    result = run_pipeline_collect(ACME)["result"]

    assert result["validate"]["passed"]
    assert result["match"]["vendor_match"]["matched"]
    po = result["match"]["po_match"]
    assert po["matched"] and po["po_number"] == "PO-7841" and po["match_type"] == "explicit"

    amount = result["match"]["amount_check"]
    assert amount["difference"] == 27.20
    assert amount["tolerance"] == 50.00
    assert amount["within_tolerance"] and amount["billing_mode"] == "full"

    assert result["decide"]["decision"] == "auto_approve"
    assert "$27.20" in result["decide"]["explanation"]


def test_meridian_happy_path_exact_match():
    result = run_pipeline_collect(MERIDIAN)["result"]
    amount = result["match"]["amount_check"]
    assert amount["difference"] == 0.0 and amount["within_tolerance"]
    assert result["decide"]["decision"] == "auto_approve"


def test_rules_trace_is_complete_and_auditable():
    decision = run_pipeline_collect(ACME)["result"]["decide"]
    rules = [r["rule"] for r in decision["rules_trace"]]
    # every rule appears in the trace, triggered or not - R0 (prompt injection)
    # and R8 (auto-approval cap) are the guardrails-layer additions
    assert [r.split("_")[0] for r in rules] == \
        ["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
    assert not any(r["triggered"] for r in decision["rules_trace"])
    assert all(r["detail"] for r in decision["rules_trace"])


def test_duplicate_rule_fires_against_prior_runs():
    prior = [{
        "invoice_number": "INV-2026-0847",
        "vendor_name": "Acme Office Supplies Ltd.",
        "po_ref": "PO-7841",
        "total": 2527.20,
        "run_id": 1,
    }]
    result = run_pipeline_collect(ACME, prior_invoices=prior)["result"]
    assert result["decide"]["decision"] == "reject"
    fired = [r for r in result["decide"]["rules_trace"] if r["triggered"]]
    assert fired[0]["rule"] == "R1_duplicate_invoice"
