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
from datetime import datetime, timedelta, timezone
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
    decision_reason TEXT,
    invoice_number TEXT,
    vendor_name TEXT,
    invoice_date TEXT,
    po_ref TEXT,
    total REAL,
    error TEXT,
    trace_json TEXT
);
CREATE TABLE IF NOT EXISTS run_events (
    run_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    event_json TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS worker_tasks (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_needed INTEGER NOT NULL DEFAULT 0,
    events_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT
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
        columns = {row["name"] for row in con.execute("PRAGMA table_info(runs)")}
        if "decision_reason" not in columns:
            con.execute("ALTER TABLE runs ADD COLUMN decision_reason TEXT")
        # Preserve explainability for completed records written before this
        # column existed by deriving the stored reason from their real trace.
        rows = con.execute(
            "SELECT id, trace_json FROM runs "
            "WHERE status='completed' AND decision_reason IS NULL AND trace_json IS NOT NULL"
        ).fetchall()
        for row in rows:
            try:
                trace = json.loads(row["trace_json"])
                reason = trace.get("decide", {}).get("primary_reason")
            except (AttributeError, TypeError, json.JSONDecodeError):
                reason = None
            if reason:
                con.execute("UPDATE runs SET decision_reason=? WHERE id=?", (reason, row["id"]))


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
            "UPDATE runs SET status='completed', decision=?, decision_reason=?, invoice_number=?, vendor_name=?, "
            "invoice_date=?, po_ref=?, total=?, trace_json=? WHERE id=? AND status='running'",
            (result["decide"]["decision"], result["decide"].get("primary_reason"),
             inv["invoice_number"], inv["vendor_name"],
             inv["invoice_date"], inv["po_ref"], inv["total"], json.dumps(result), run_id),
        )


def fail_run(run_id: int, error: str) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE runs SET status='failed', error=?, trace_json=? WHERE id=? AND status='running'",
            (error, json.dumps({"error": error}), run_id),
        )


def append_run_event(run_id: int, event: dict) -> None:
    with _connect() as con:
        sequence = con.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 FROM run_events WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        con.execute(
            "INSERT INTO run_events (run_id, sequence, event_json) VALUES (?, ?, ?)",
            (run_id, sequence, json.dumps(event)),
        )


def list_run_events(run_id: int, after_sequence: int = -1) -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT event_json FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence",
            (run_id, after_sequence),
        ).fetchall()
    return [json.loads(row["event_json"]) for row in rows]


def mark_stale_runs(max_age_seconds: int = 180) -> int:
    """Fail runs left running beyond the configured recovery window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)).isoformat(timespec="seconds")
    error = f"Run exceeded the {max_age_seconds}-second processing limit and was marked failed by the stale-run guard."
    with _connect() as con:
        stale = con.execute(
            "SELECT id FROM runs WHERE status='running' AND created_at < ?", (cutoff,)
        ).fetchall()
        for row in stale:
            run_id = row["id"]
            con.execute(
                "UPDATE runs SET status='failed', error=?, trace_json=? WHERE id=? AND status='running'",
                (error, json.dumps({"error": error}), run_id),
            )
            sequence = con.execute(
                "SELECT COALESCE(MAX(sequence), -1) + 1 FROM run_events WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            con.execute(
                "INSERT INTO run_events (run_id, sequence, event_json) VALUES (?, ?, ?)",
                (run_id, sequence, json.dumps({"stage": "pipeline", "status": "failed", "error": error})),
            )
        return len(stale)


def list_runs() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id, created_at, filename, scenario, status, decision, decision_reason, invoice_number, "
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


def create_worker_task(task_id: str, task: str) -> None:
    with _connect() as con:
        con.execute(
            "INSERT INTO worker_tasks (id, task, created_at, status) VALUES (?, ?, ?, 'pending')",
            (task_id, task, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def update_worker_task(
    task_id: str,
    *,
    status: str,
    events: list[dict],
    approval_needed: bool = False,
    result: dict | None = None,
) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE worker_tasks SET status=?, approval_needed=?, events_json=?, result_json=? WHERE id=?",
            (status, int(approval_needed), json.dumps(events),
             json.dumps(result) if result is not None else None, task_id),
        )


def get_worker_task(task_id: str) -> dict | None:
    with _connect() as con:
        row = con.execute("SELECT * FROM worker_tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        return None
    task = dict(row)
    task["approval_needed"] = bool(task["approval_needed"])
    task["events"] = json.loads(task.pop("events_json"))
    task["result"] = json.loads(task.pop("result_json")) if task.get("result_json") else None
    return task


def list_worker_tasks() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id, task, created_at, status, approval_needed, events_json, result_json "
            "FROM worker_tasks ORDER BY created_at DESC"
        ).fetchall()
    tasks = []
    for row in rows:
        task = {key: row[key] for key in ("id", "task", "created_at", "status")}
        task["approval_needed"] = bool(row["approval_needed"])
        task["events"] = json.loads(row["events_json"])
        task["result"] = json.loads(row["result_json"]) if row["result_json"] else None
        tasks.append(task)
    return tasks


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
