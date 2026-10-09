"""Tools available to the Autonomous AI Task Worker.

These tools allow the worker to:
1. Search and locate files/invoices on the computer.
2. Inspect document metadata and text layers.
3. Execute the full CentrAlign AI 5-stage verification pipeline.
4. Query internal master records (vendors & purchase orders).
5. Ingest invoices into the internal accounting/ERP system.
6. Deterministically verify whether the outcome was recorded in the database.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from app import config, db
from app.guardrails.file_validation import sanitize_filename, validate_upload
from app.pipeline.run import run_pipeline


def find_files(query: str, search_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Search for invoice documents matching a query (filename, vendor name, or keyword).
    
    Returns a sorted list of matching files with path, name, size_bytes, and modified_time.
    """
    search_dirs = []
    if search_dir:
        search_dirs.append(Path(search_dir))
    else:
        # The live worker only searches documents explicitly placed in the
        # user-upload area. Test fixtures and repository files are never
        # treated as company documents.
        search_dirs.append(config.UPLOAD_DIR)

    generic_terms = {"the", "latest", "newest", "recent", "most", "from", "company", "invoice", "invoices", "and", "our", "all", "any", "document", "documents", "pdf"}
    tokens = [
        token.lower() for token in re.split(r"[\s_-]+", query)
        if token and token.lower() not in generic_terms
    ]
    broad_search = not tokens

    matches: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()

    for d in search_dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.pdf"):
            if p in seen_paths:
                continue
            seen_paths.add(p)
            name_lower = p.name.lower()
            stem_lower = p.stem.lower()

            # Score match
            match_score = 0
            for token in tokens:
                if token in name_lower or token in stem_lower:
                    match_score += 10
            
            # Generic invoice requests search all uploaded PDFs; relevance is
            # then determined by the user-requested latest/clarification flow.
            if broad_search:
                match_score = max(match_score, 1)

            if match_score > 0:
                if "_injection" in name_lower and "injection" not in query.lower():
                    match_score -= 5
                if "_resubmitted" in name_lower and "resubmit" not in query.lower() and "duplicate" not in query.lower():
                    match_score -= 2
                stat = p.stat()
                matches.append({
                    "path": str(p.resolve()),
                    "filename": p.name,
                    "size_bytes": stat.st_size,
                    "modified_time": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "score": match_score,
                })

    # Prefer query relevance, then newest matching user-provided document.
    matches.sort(key=lambda m: (m["score"], m["modified_time"]), reverse=True)
    return matches


def read_document_metadata(file_path: str | Path) -> dict[str, Any]:
    """Inspect a document's physical properties, header bytes, and text layer."""
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}

    content = p.read_bytes()
    try:
        validate_upload(p.name, content)
        valid_pdf = True
        validation_error = None
    except Exception as e:
        valid_pdf = False
        validation_error = str(e)

    # Text extraction check
    import fitz
    text_chars = 0
    page_count = 0
    try:
        with fitz.open(p) as doc:
            page_count = doc.page_count
            text_chars = sum(len(page.get_text().strip()) for page in doc)
    except Exception as err:
        return {"error": f"Failed to parse PDF structure: {err}"}

    return {
        "filename": p.name,
        "file_size": len(content),
        "is_valid_pdf": valid_pdf,
        "validation_error": validation_error,
        "page_count": page_count,
        "text_chars": text_chars,
        "is_text_native": text_chars >= 100 * max(page_count, 1),
    }


def execute_pipeline(file_path: str | Path) -> dict[str, Any]:
    """Run CentrAlign AI's five-stage verification pipeline on an invoice file."""
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}

    prior = db.prior_invoices()
    final_result = None

    for event in run_pipeline(p, prior):
        if event.get("stage") == "pipeline":
            if event.get("status") == "completed":
                final_result = event.get("result")
            elif event.get("status") == "failed":
                return {"error": event.get("error", "Pipeline execution failed")}

    if not final_result:
        return {"error": "Pipeline produced no result"}

    inv = final_result["invoice"]
    dec = final_result["decide"]
    return {
        "invoice_number": inv.get("invoice_number"),
        "vendor_name": inv.get("vendor_name"),
        "invoice_date": inv.get("invoice_date"),
        "due_date": final_result["extract"]["fields"].get("due_date", {}).get("value"),
        "po_ref": inv.get("po_ref"),
        "subtotal": final_result["extract"]["fields"].get("subtotal", {}).get("value"),
        "tax": final_result["extract"]["fields"].get("tax", {}).get("value"),
        "total": inv.get("total"),
        "decision": dec.get("decision"),
        "primary_reason": dec.get("primary_reason"),
        "guardrails_flagged": final_result["guardrails"].get("flagged", False),
        "validation_passed": final_result["validate"].get("passed", False),
        "raw_trace": final_result,
    }


def query_master_records(query_type: str, search_term: str = "") -> list[dict[str, Any]]:
    """Query master records: 'vendors' or 'purchase_orders'."""
    term = search_term.lower().strip()
    if query_type.lower() in {"vendor", "vendors"}:
        vendors = db.get_vendors()
        if not term:
            return vendors
        return [
            v for v in vendors
            if term in v["name"].lower()
            or term in v["vendor_id"].lower()
            or any(term in a.lower() for a in v["aliases"])
        ]
    elif query_type.lower() in {"po", "pos", "purchase_order", "purchase_orders"}:
        pos = db.get_purchase_orders()
        if not term:
            return pos
        return [
            p for p in pos
            if term in p["po_number"].lower()
            or term in p["vendor_id"].lower()
            or term in (p.get("description") or "").lower()
        ]
    return []


def ingest_into_internal_system(file_path: str | Path) -> dict[str, Any]:
    """Ingest the invoice into the internal system: validates, persists run in SQLite, and books record."""
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}

    content = p.read_bytes()
    validate_upload(p.name, content)

    safe_name = sanitize_filename(p.name)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = config.UPLOAD_DIR / f"{stamp}_{safe_name}"
    stored.write_bytes(content)

    run_id = db.create_run(safe_name, str(stored))
    prior = db.prior_invoices()
    final = None

    for event in run_pipeline(stored, prior):
        if event.get("stage") == "pipeline":
            final = event

    if final and final.get("status") == "completed":
        inv = final["result"]["invoice"]
        dec = final["result"]["decide"]
        if dec.get("decision") == "reject":
            reason = dec.get("primary_reason") or "Deterministic rules rejected this invoice."
            db.fail_run(run_id, f"Not ingested: {reason}")
            return {
                "success": False,
                "run_id": run_id,
                "error": f"Not ingested: deterministic rules rejected the invoice. {reason}",
                "decision": "reject",
            }
        db.complete_run(run_id, final["result"])
        return {
            "success": True,
            "run_id": run_id,
            "invoice_number": inv.get("invoice_number"),
            "vendor_name": inv.get("vendor_name"),
            "total": inv.get("total"),
            "decision": dec.get("decision"),
            "reason": dec.get("primary_reason"),
            "stored_path": str(stored),
        }
    else:
        err = (final or {}).get("error", "Internal pipeline ingestion failed")
        db.fail_run(run_id, err)
        return {
            "success": False,
            "run_id": run_id,
            "error": err,
        }


def verify_outcome(
    invoice_number: str | None = None,
    run_id: int | None = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify whether the requested outcome was actually achieved in the internal database."""
    if run_id is not None:
        run = db.get_run(run_id)
        if not run:
            return {"verified": False, "reason": f"No record exists in database for run_id {run_id}"}
        trace = run.get("trace") or {}
        fields = trace.get("extract", {}).get("fields", {})
        actual = {
            "invoice_number": run.get("invoice_number"),
            "vendor_name": run.get("vendor_name"),
            "total": run.get("total"),
            "due_date": (fields.get("due_date") or {}).get("value"),
        }
        mismatches = {}
        missing_expected = []
        for key, expected_value in (expected or {}).items():
            actual_value = actual.get(key)
            if expected_value is None:
                missing_expected.append(key)
                continue
            if key == "total" and expected_value is not None and actual_value is not None:
                matches = abs(float(actual_value) - float(expected_value)) < 0.01
            else:
                matches = (
                    actual_value is not None
                    and str(actual_value).strip().casefold() == str(expected_value).strip().casefold()
                )
            if not matches:
                mismatches[key] = {"expected": expected_value, "actual": actual_value}
        decision_recorded = run["status"] == "completed" and run["decision"] in {"auto_approve", "needs_review"}
        reason = None
        if missing_expected:
            reason = "Could not verify fields that extraction did not provide: " + ", ".join(missing_expected)
        elif mismatches:
            reason = "Persisted fields differ from extracted values"
        return {
            "verified": decision_recorded and not mismatches and not missing_expected,
            "recorded": run["status"] == "completed",
            "approved": run["decision"] == "auto_approve",
            "field_mismatches": mismatches,
            "unverified_fields": missing_expected,
            "reason": reason,
            "run_id": run["id"],
            "status": run["status"],
            "decision": run["decision"],
            "invoice_number": run["invoice_number"],
            "vendor_name": run["vendor_name"],
            "total": run["total"],
            "due_date": actual["due_date"],
            "stored_path": run["stored_path"],
            "created_at": run["created_at"],
        }

    if invoice_number:
        runs = db.list_runs()
        match = next((r for r in runs if r.get("invoice_number") == invoice_number), None)
        if not match:
            return {"verified": False, "reason": f"Invoice '{invoice_number}' not found in internal system"}
        return {
            "verified": match["status"] == "completed" and match["decision"] in {"auto_approve", "needs_review"},
            "recorded": match["status"] == "completed",
            "approved": match["decision"] == "auto_approve",
            "run_id": match["id"],
            "status": match["status"],
            "decision": match["decision"],
            "invoice_number": match["invoice_number"],
            "vendor_name": match["vendor_name"],
            "total": match["total"],
        }

    return {"verified": False, "reason": "Neither run_id nor invoice_number provided"}
