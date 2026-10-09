"""Verification of the 10 core CentrAlign AI test scenarios:

1. A valid text-based invoice.
2. A scanned invoice.
3. A document with missing or uncertain fields.
4. An invoice containing a prompt-injection attempt.
5. An unknown vendor or missing purchase order.
6. A duplicate invoice.
7. An invoice exceeding the auto-approval limit.
8. An invalid or oversized upload.
9. An application started with an empty database.
10. A processing failure or unavailable extraction service.

Plus verification that ZERO HALLUCINATION and ZERO FABRICATION are prominently
rendered in the interface and that no synthetic fixtures populate the live app.
"""

import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from app import config, db
from app.api import app
from app.config import FIXTURE_INVOICE_DIR, GROQ_API_KEY
from app.guardrails.file_validation import MAX_UPLOAD_SIZE_BYTES
from app.pipeline.decide import AUTO_APPROVAL_MAX_AMOUNT, AUTO_APPROVE, NEEDS_REVIEW, REJECT
from tests.helpers import upload_fixture


# -----------------------------------------------------------------------------
# Scenario 1: A valid text-based invoice
# -----------------------------------------------------------------------------
def test_scenario_1_valid_text_invoice():
    with TestClient(app) as c:
        res = upload_fixture(c, "INV-2026-0847_acme.pdf")
        assert res["status"] == "completed"
        result = res["result"]

        # 5 stages completed
        assert result["extract"]["method"] == "text"
        assert result["extract"]["extraction_confidence"] >= 0.85
        assert result["guardrails"]["flagged"] is False
        assert result["validate"]["passed"] is True
        assert result["match"]["vendor_match"]["matched"] is True
        assert result["match"]["po_match"]["matched"] is True

        # Decision
        assert result["decide"]["decision"] == AUTO_APPROVE
        assert "approved" in result["decide"]["primary_reason"].lower() or "passed" in result["decide"]["primary_reason"].lower()


# -----------------------------------------------------------------------------
# Scenario 2: A scanned invoice
# -----------------------------------------------------------------------------
def test_scenario_2_scanned_invoice():
    with TestClient(app) as c:
        if not GROQ_API_KEY:
            # When GROQ_API_KEY is not set, must route to vision and fail loudly
            res = upload_fixture(c, "INV-3847_brightway_scanned.pdf")
            assert res["status"] == "failed"
            assert "vision" in res["error"].lower() or "groq_api_key" in res["error"].lower()
        else:
            # When GROQ_API_KEY is set, extracts via vision LLM
            res = upload_fixture(c, "INV-3847_brightway_scanned.pdf")
            assert res["status"] == "completed"
            assert res["result"]["extract"]["method"] == "vision"


# -----------------------------------------------------------------------------
# Scenario 3: A document with missing or uncertain fields
# -----------------------------------------------------------------------------
def test_scenario_3_missing_or_uncertain_fields():
    with TestClient(app) as c:
        res = upload_fixture(c, "INV-0092_vertex_no_po.pdf")
        assert res["status"] == "completed"
        result = res["result"]

        # PO ref is explicitly missing on document, not invented
        inv = result["invoice"]
        assert inv["po_ref"] is None
        assert result["extract"]["fields"]["po_ref"]["value"] is None

        # Fuzzy match finds candidate PO, but requires human confirmation (R6)
        assert result["match"]["po_match"]["match_type"] == "fuzzy_vendor_amount"
        assert result["decide"]["decision"] == NEEDS_REVIEW
        triggered_rules = [r["rule"] for r in result["decide"]["rules_trace"] if r["triggered"]]
        assert "R6_fuzzy_po_needs_confirmation" in triggered_rules


# -----------------------------------------------------------------------------
# Scenario 4: An invoice containing a prompt-injection attempt
# -----------------------------------------------------------------------------
def test_scenario_4_prompt_injection_attempt():
    with TestClient(app) as c:
        res = upload_fixture(c, "INV-2026-1099_acme_injection.pdf")
        assert res["status"] == "completed"
        result = res["result"]

        # Guardrails stage flags injection
        assert result["guardrails"]["flagged"] is True
        findings = result["guardrails"]["findings"]
        assert len(findings) > 0
        assert any("auto-approve" in f["matched_text"].lower() or "ignore" in f["matched_text"].lower() for f in findings)

        # R0 rule triggers, forcing needs_review despite clean vendor and PO match
        assert result["decide"]["decision"] == NEEDS_REVIEW
        triggered_rules = [r["rule"] for r in result["decide"]["rules_trace"] if r["triggered"]]
        assert "R0_prompt_injection_detected" in triggered_rules


# -----------------------------------------------------------------------------
# Scenario 5: An unknown vendor or missing purchase order
# -----------------------------------------------------------------------------
def test_scenario_5_unknown_vendor():
    from app.pipeline.match import match_vendor, match
    from app.pipeline.decide import decide

    # Invoice with unknown vendor
    extract_unknown = {
        "method": "text",
        "extraction_confidence": 0.95,
        "fields": {
            "invoice_number": {"value": "INV-9999", "confidence": 0.95, "source": "test"},
            "vendor_name": {"value": "Nonexistent Global LLC", "confidence": 0.95, "source": "test"},
            "invoice_date": {"value": "2026-03-01", "confidence": 0.95, "source": "test"},
            "po_ref": {"value": "PO-9999", "confidence": 0.95, "source": "test"},
            "subtotal": {"value": 100.0, "confidence": 0.95, "source": "test"},
            "tax": {"value": 0.0, "confidence": 0.95, "source": "test"},
            "total": {"value": 100.0, "confidence": 0.95, "source": "test"},
        },
        "line_items": [],
    }

    match_res = match(extract_unknown)
    assert match_res["vendor_match"]["matched"] is False

    val = {"passed": True, "checks": [{"name": "required", "passed": True, "detail": "ok"}]}
    dec = decide(extract_unknown, val, match_res)
    assert dec["decision"] == REJECT
    triggered = [r["rule"] for r in dec["rules_trace"] if r["triggered"]]
    assert "R3_vendor_unknown_or_unapproved" in triggered


# -----------------------------------------------------------------------------
# Scenario 6: A duplicate invoice
# -----------------------------------------------------------------------------
def test_scenario_6_duplicate_invoice():
    with TestClient(app) as c:
        # First processing succeeds
        r1 = upload_fixture(c, "INV-8613_meridian.pdf")
        assert r1["status"] == "completed"
        assert r1["result"]["decide"]["decision"] == AUTO_APPROVE

        # Second processing of the exact same invoice
        r2 = upload_fixture(c, "INV-8613_meridian.pdf")
        assert r2["status"] == "completed"
        assert r2["result"]["decide"]["decision"] == REJECT
        triggered = [r["rule"] for r in r2["result"]["decide"]["rules_trace"] if r["triggered"]]
        assert "R1_duplicate_invoice" in triggered


# -----------------------------------------------------------------------------
# Scenario 7: An invoice exceeding the auto-approval limit
# -----------------------------------------------------------------------------
def test_scenario_7_invoice_exceeding_auto_approval_limit():
    from app.pipeline.decide import decide

    extract_large = {
        "method": "text",
        "extraction_confidence": 0.95,
        "fields": {
            "invoice_number": {"value": "INV-BIG", "confidence": 0.95, "source": "test"},
            "vendor_name": {"value": "Acme Corp", "confidence": 0.95, "source": "test"},
            "invoice_date": {"value": "2026-03-01", "confidence": 0.95, "source": "test"},
            "po_ref": {"value": "PO-1", "confidence": 0.95, "source": "test"},
            "subtotal": {"value": 30000.0, "confidence": 0.95, "source": "test"},
            "tax": {"value": 0.0, "confidence": 0.95, "source": "test"},
            "total": {"value": 30000.0, "confidence": 0.95, "source": "test"},
        },
        "line_items": [],
    }

    match_res = {
        "vendor_match": {"matched": True, "vendor_id": "V-1", "vendor_name": "Acme Corp", "approved": True, "detail": "ok"},
        "po_match": {"matched": True, "po_number": "PO-1", "match_type": "explicit", "detail": "ok"},
        "amount_check": {
            "po_amount": 30000.0,
            "invoice_total": 30000.0,
            "tolerance": 500.0,
            "tolerance_rule": "rule",
            "difference": 0.0,
            "within_tolerance": True,
            "billing_mode": "full",
        },
    }
    val = {"passed": True, "checks": [{"name": "sanity", "passed": True, "detail": "ok"}]}

    dec = decide(extract_large, val, match_res)
    assert dec["decision"] == NEEDS_REVIEW
    triggered = [r["rule"] for r in dec["rules_trace"] if r["triggered"]]
    assert "R8_amount_exceeds_auto_approval_cap" in triggered


# -----------------------------------------------------------------------------
# Scenario 8: An invalid or oversized upload
# -----------------------------------------------------------------------------
def test_scenario_8_invalid_or_oversized_upload():
    with TestClient(app) as c:
        # 1. Non-pdf extension
        res = c.post("/api/invoices", files={"file": ("test.txt", b"plain text", "text/plain")})
        assert res.status_code == 400
        assert "pdf" in res.json()["detail"].lower()

        # 2. Empty file
        res = c.post("/api/invoices", files={"file": ("empty.pdf", b"", "application/pdf")})
        assert res.status_code == 400
        assert "empty" in res.json()["detail"].lower()

        # 3. Corrupt missing %PDF magic bytes
        res = c.post("/api/invoices", files={"file": ("fake.pdf", b"NOT_A_REAL_PDF_HEADER", "application/pdf")})
        assert res.status_code == 400
        assert "valid pdf" in res.json()["detail"].lower()

        # 4. Oversized file
        oversized = b"%PDF-" + b"0" * (MAX_UPLOAD_SIZE_BYTES + 1024)
        res = c.post("/api/invoices", files={"file": ("huge.pdf", oversized, "application/pdf")})
        assert res.status_code == 400
        assert "exceeds" in res.json()["detail"].lower()


# -----------------------------------------------------------------------------
# Scenario 9: Application started with an empty database
# -----------------------------------------------------------------------------
def test_scenario_9_empty_database_indicates_matching_uncompletable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "empty_scenario.db")
    db.init_db()

    # Master database is empty
    assert db.get_vendors() == []
    assert db.get_purchase_orders() == []

    from app.pipeline.match import match
    from app.pipeline.decide import decide

    sample_extract = {
        "method": "text",
        "extraction_confidence": 0.95,
        "fields": {
            "invoice_number": {"value": "INV-100", "confidence": 0.95, "source": "test"},
            "vendor_name": {"value": "Acme Corp", "confidence": 0.95, "source": "test"},
            "invoice_date": {"value": "2026-03-01", "confidence": 0.95, "source": "test"},
            "po_ref": {"value": "PO-1", "confidence": 0.95, "source": "test"},
            "subtotal": {"value": 500.0, "confidence": 0.95, "source": "test"},
            "tax": {"value": 0.0, "confidence": 0.95, "source": "test"},
            "total": {"value": 500.0, "confidence": 0.95, "source": "test"},
        },
        "line_items": [],
    }

    match_res = match(sample_extract)
    assert match_res["vendor_match"]["matched"] is False
    assert "no vendor records configured" in match_res["vendor_match"]["detail"]

    val = {"passed": True, "checks": [{"name": "check", "passed": True, "detail": "ok"}]}
    dec = decide(sample_extract, val, match_res)
    # Never auto-approves with empty database; rejects because vendor cannot be matched
    assert dec["decision"] == REJECT
    assert "no vendor records configured" in dec["primary_reason"]


# -----------------------------------------------------------------------------
# Scenario 10: Processing failure or unavailable extraction service
# -----------------------------------------------------------------------------
def test_scenario_10_processing_failure_records_as_failed(tmp_path, monkeypatch):
    with TestClient(app) as c:
        # Uploading scanned invoice when vision service is unconfigured
        monkeypatch.setattr(config, "GROQ_API_KEY", "")
        res = upload_fixture(c, "INV-3847_brightway_scanned.pdf")

        # Run fails and is recorded as failed, never reported as success
        assert res["status"] == "failed"
        assert res["error"] is not None

        run_id = res["run_id"]
        run_record = c.get(f"/api/runs/{run_id}").json()
        assert run_record["status"] == "failed"
        assert run_record["decision"] is None
        assert run_record["error"] is not None


# -----------------------------------------------------------------------------
# UI Principles & Branding Verification
# -----------------------------------------------------------------------------
def test_ui_keeps_branding_without_removed_principle_cards():
    with TestClient(app) as c:
        res = c.get("/")
        assert res.status_code == 200
        html = res.text

        # Must have CentrAlign AI branding
        assert "CentrAlign AI" in html
        assert "Invoice Processing Automation" in html

        # The removed slogans must not be present in the served UI shell.
        assert "ZERO HALLUCINATION" not in html
        assert "ZERO FABRICATION" not in html

        # Must not have sample invoices endpoint or baked fixture samples
        sample_res = c.get("/api/samples")
        assert sample_res.status_code == 404
