# Root conftest: puts the project root on sys.path and gives every test an
# isolated SQLite DB (never touches data/runs.db) seeded with the fabricated
# fixtures/ vendor+PO dataset - fabricated data is fine for the test suite
# (per the case-study brief), it just never ships inside the running app.

import pytest

from app import config, db

FIXTURES_DIR = config.ROOT / "fixtures"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test_runs.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    db.init_db()
    db.seed_master_data(FIXTURES_DIR / "vendors.json", FIXTURES_DIR / "purchase_orders.json")
    yield
