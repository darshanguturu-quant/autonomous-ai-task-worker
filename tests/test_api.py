"""API integration tests: upload/run -> persisted -> dashboard -> trace reopen."""

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.config import GROQ_API_KEY
from app.pipeline.extract import read_text_layer
from tests.helpers import FIXTURE_INVOICE_DIR, upload_fixture


def test_upload_run_persists_and_trace_is_reopenable():
    with TestClient(app) as c:
        data = upload_fixture(c, "INV-2026-0847_acme.pdf")
        assert data["status"] == "completed"
        assert data["result"]["decide"]["decision"] == "auto_approve"

        runs = c.get("/api/runs").json()
        assert runs[0]["id"] == data["run_id"]
        assert runs[0]["invoice_number"] == "INV-2026-0847"
        assert runs[0]["decision"] == "auto_approve"

        detail = c.get(f"/api/runs/{data['run_id']}").json()
        assert detail["trace"]["match"]["po_match"]["po_number"] == "PO-7841"
        assert set(detail["trace"]) >= \
            {"invoice", "extract", "guardrails", "validate", "match", "decide"}


def test_upload_endpoint_processes_real_pdf():
    with TestClient(app) as c:
        pdf = (FIXTURE_INVOICE_DIR / "INV-8613_meridian.pdf").read_bytes()
        r = c.post("/api/invoices",
                   files={"file": ("INV-8613_meridian.pdf", pdf, "application/pdf")})
        assert r.status_code == 200
        assert r.json()["result"]["decide"]["decision"] == "auto_approve"


def test_duplicate_detection_uses_persisted_prior_runs():
    with TestClient(app) as c:
        first = upload_fixture(c, "INV-2026-0847_acme.pdf")
        assert first["result"]["decide"]["decision"] == "auto_approve"
        # different file bytes, same invoice fields -> field-based duplicate reject
        second = upload_fixture(c, "INV-2026-0847_acme_resubmitted.pdf")
        assert second["result"]["decide"]["decision"] == "reject"
        assert "duplicate" in second["result"]["decide"]["primary_reason"]


def test_duplicate_decision_variance_is_explained_in_run_record():
    with TestClient(app) as client:
        first = upload_fixture(client, "INV-8613_meridian.pdf")
        second = upload_fixture(client, "INV-8613_meridian.pdf")
        assert first["result"]["invoice"] == second["result"]["invoice"]
        assert first["result"]["decide"]["decision"] == "auto_approve"
        assert second["result"]["decide"]["decision"] == "reject"
        runs = client.get("/api/runs").json()
        assert runs[0]["decision_reason"]
        assert "duplicate" in runs[0]["decision_reason"].lower()


def test_database_migration_backfills_historical_decision_reason():
    from app import db

    run_id = db.create_run("historical.pdf", "historical.pdf")
    db.complete_run(run_id, {
        "invoice": {
            "invoice_number": "INV-HIST", "vendor_name": "Wayne Enterprises",
            "invoice_date": "2026-10-01", "po_ref": "PO-1", "total": 12500.0,
        },
        "decide": {
            "decision": "reject",
            "primary_reason": "duplicate of run 4",
        },
    })
    with db._connect() as con:
        con.execute("UPDATE runs SET decision_reason=NULL WHERE id=?", (run_id,))

    db.init_db()

    saved = next(run for run in db.list_runs() if run["id"] == run_id)
    assert saved["decision_reason"] == "duplicate of run 4"


@pytest.mark.parametrize(("filename", "expected"), [
    ("INV-2026-1099_acme_injection.pdf", {
        "invoice_number": "INV-2026-1099", "vendor_name": "Acme Office Supplies Ltd.",
        "total": 2527.2, "due_date": "2026-08-18", "po_ref": "PO-7841",
    }),
    ("INV-0092_vertex_no_po.pdf", {
        "invoice_number": "INV-0092", "vendor_name": "Vertex Marketing Group",
        "total": 5750.5, "due_date": "2026-08-15", "po_ref": None,
    }),
    ("INV-8613_meridian.pdf", {
        "invoice_number": "INV-8613", "vendor_name": "Meridian IT Services LLC",
        "total": 9168.25, "due_date": "2026-08-13", "po_ref": "PO-7852",
    }),
])
def test_requested_invoice_regression_extraction(filename, expected):
    with TestClient(app) as client:
        response = upload_fixture(client, filename)
        assert response["status"] == "completed"
        result = response["result"]
        invoice = result["invoice"]
        assert invoice["invoice_number"] == expected["invoice_number"]
        assert invoice["vendor_name"] == expected["vendor_name"]
        assert invoice["total"] == expected["total"]
        currency = result["extract"]["fields"]["currency"]
        document_text, _ = read_text_layer(FIXTURE_INVOICE_DIR / filename)
        if "USD" in document_text:
            assert currency["value"] == "USD"
        else:
            assert currency["value"] is None
        assert result["extract"]["fields"]["due_date"]["value"] == expected["due_date"]
        assert invoice["po_ref"] == expected["po_ref"]
        if "injection" in filename:
            assert result["guardrails"]["flagged"] is True
            assert result["decide"]["decision"] != "auto_approve"


def test_clear_history_resets_duplicate_state():
    with TestClient(app) as c:
        upload_fixture(c, "INV-2026-0847_acme.pdf")
        c.delete("/api/runs")
        assert c.get("/api/runs").json() == []
        rerun = upload_fixture(c, "INV-2026-0847_acme.pdf")
        assert rerun["result"]["decide"]["decision"] == "auto_approve"


@pytest.mark.skipif(bool(GROQ_API_KEY),
                    reason="key configured - scanned fixture succeeds via vision instead")
def test_scanned_pdf_without_api_key_fails_loudly_not_silently():
    with TestClient(app) as c:
        r = upload_fixture(c, "INV-3847_brightway_scanned.pdf")
        # without a key, the vision path must fail with a clear error, not silently
        assert r["status"] == "failed"
        assert "vision" in r["error"].lower() or "GROQ_API_KEY" in r["error"]
        runs = c.get("/api/runs").json()
        assert runs[0]["status"] == "failed"


def test_frontend_served_at_root():
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "Invoice Processing Automation" in r.text


def test_curated_sample_downloads_are_explicit_and_never_auto_processed():
    """Only explicitly requested, allowlisted fixture PDFs can be downloaded."""
    with TestClient(app) as c:
        examples = c.get("/api/examples").json()["examples"]
        assert len(examples) == 3
        assert c.get("/api/examples/not-allowlisted.pdf").status_code == 404

        download = c.get(examples[0]["download_url"])
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/pdf"
        assert "attachment" in download.headers["content-disposition"]

        assert c.get("/api/runs").json() == []


def test_app_starts_with_zero_vendors_and_pos_until_explicitly_seeded(tmp_path, monkeypatch):
    """Guards against silently reintroducing auto-seeded fabricated data.

    Uses its own fresh DB path (not the autouse-seeded one from conftest) so
    this specifically proves init_db() alone - no seed call - stays empty."""
    from app import config, db
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "truly_fresh.db")
    db.init_db()  # schema only, no seed - mirrors what api.py's lifespan does
    assert db.get_vendors() == []
    assert db.get_purchase_orders() == []
