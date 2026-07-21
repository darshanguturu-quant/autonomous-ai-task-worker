"""API integration tests: upload/run -> persisted -> dashboard -> trace reopen."""

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.config import GROQ_API_KEY
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


def test_no_samples_endpoint_ships_in_the_app():
    """The live app must never expose bundled/fabricated demo data."""
    with TestClient(app) as c:
        assert c.get("/api/samples").status_code == 404
        # No route handles this POST; falls through to the SPA static-files
        # catch-all mount, which only supports GET/HEAD -> 405, not a run.
        r = c.post("/api/samples/anything.pdf/run")
        assert r.status_code in (404, 405)


def test_app_starts_with_zero_vendors_and_pos_until_explicitly_seeded(tmp_path, monkeypatch):
    """Guards against silently reintroducing auto-seeded fabricated data.

    Uses its own fresh DB path (not the autouse-seeded one from conftest) so
    this specifically proves init_db() alone - no seed call - stays empty."""
    from app import config, db
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "truly_fresh.db")
    db.init_db()  # schema only, no seed - mirrors what api.py's lifespan does
    assert db.get_vendors() == []
    assert db.get_purchase_orders() == []
