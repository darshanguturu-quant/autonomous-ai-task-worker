"""SQLite storage: runs (with full stage traces) + the vendor/PO master dataset.

The live app never auto-loads vendor/PO data - init_db() only creates the
schema, so a freshly started app has zero vendors and zero POs (nothing can
auto-approve until real data is loaded). seed_master_data() is an explicit,
opt-in utility for loading a vendor/PO dataset (e.g. fixtures/vendors.json
during local testing) - it is never called automatically by the app.

Each pipeline run is stored with its complete per-stage trace so the
dashboard can reopen any run.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    address TEXT,
    approved INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    description TEXT,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    tolerance_pct REAL NOT NULL,
    tolerance_abs REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    scenario TEXT,
    status TEXT NOT NULL,               -- running | completed | failed
    decision TEXT,                      -- auto_approve | needs_review | reject
    invoice_number TEXT,
    vendor_name TEXT,
    invoice_date TEXT,
    po_ref TEXT,
    total REAL,
    error TEXT,
    trace_json TEXT
);
"""


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db() -> None:
    """Create the schema only. Never auto-seeds - a freshly started app has
    zero vendors and zero POs until seed_master_data() is called explicitly."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript(SCHEMA)


def seed_master_data(vendors_path: Path, purchase_orders_path: Path) -> None:
    """Explicit, opt-in load of a vendor/PO dataset from two JSON files.

    Not called by the running app. Intended for local testing/demo prep
    (e.g. against fixtures/vendors.json + fixtures/purchase_orders.json) or
    for loading a real company's actual vendor/PO export."""
    vendors = json.loads(vendors_path.read_text())
    pos = json.loads(purchase_orders_path.read_text())
    with _connect() as con:
        con.execute("DELETE FROM vendors")
        con.execute("DELETE FROM purchase_orders")
        con.executemany(
            "INSERT INTO vendors VALUES (:vendor_id, :name, :aliases_json, :address, :approved)",
            [{**v, "aliases_json": json.dumps(v["aliases"]), "approved": int(v["approved"])}
             for v in vendors],
        )
        con.executemany(
            "INSERT INTO purchase_orders VALUES (:po_number, :vendor_id, :description, :amount, "
            ":currency, :status, :tolerance_pct, :tolerance_abs)",
            pos,
        )


# -- master data reads (used by the Match stage) ---------------------------

def get_vendors() -> list[dict]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM vendors").fetchall()
    return [{
        "vendor_id": r["vendor_id"], "name": r["name"],
        "aliases": json.loads(r["aliases_json"]),
        "address": r["address"], "approved": bool(r["approved"]),
    } for r in rows]


def get_purchase_orders() -> list[dict]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM purchase_orders").fetchall()
    return [dict(r) for r in rows]


# -- runs ------------------------------------------------------------------

def create_run(filename: str, stored_path: str, scenario: str | None = None) -> int:
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO runs (created_at, filename, stored_path, scenario, status) "
            "VALUES (?, ?, ?, ?, 'running')",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), filename,
             stored_path, scenario),
        )
        return cur.lastrowid


def complete_run(run_id: int, result: dict) -> None:
    inv = result["invoice"]
    with _connect() as con:
        con.execute(
            "UPDATE runs SET status='completed', decision=?, invoice_number=?, vendor_name=?, "
            "invoice_date=?, po_ref=?, total=?, trace_json=? WHERE id=?",
            (result["decide"]["decision"], inv["invoice_number"], inv["vendor_name"],
             inv["invoice_date"], inv["po_ref"], inv["total"], json.dumps(result), run_id),
        )


def fail_run(run_id: int, error: str) -> None:
    with _connect() as con:
        con.execute("UPDATE runs SET status='failed', error=? WHERE id=?", (error, run_id))


def list_runs() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id, created_at, filename, scenario, status, decision, invoice_number, "
            "vendor_name, invoice_date, po_ref, total, error FROM runs ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_run(run_id: int) -> dict | None:
    with _connect() as con:
        row = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["trace"] = json.loads(run.pop("trace_json")) if run.get("trace_json") else None
    return run


def delete_all_runs() -> int:
    """Demo reset: clear run history (duplicate/cumulative state starts fresh)."""
    with _connect() as con:
        return con.execute("DELETE FROM runs").rowcount


def prior_invoices() -> list[dict]:
    """Non-rejected completed runs - the basis for duplicate detection and
    cumulative billed-to-date. Rejected runs don't count as booked invoices."""
    with _connect() as con:
        rows = con.execute(
            "SELECT id, invoice_number, vendor_name, po_ref, total FROM runs "
            "WHERE status='completed' AND decision IN ('auto_approve', 'needs_review') "
            "ORDER BY id"
        ).fetchall()
    return [{
        "run_id": r["id"], "invoice_number": r["invoice_number"],
        "vendor_name": r["vendor_name"], "po_ref": r["po_ref"], "total": r["total"],
    } for r in rows]
