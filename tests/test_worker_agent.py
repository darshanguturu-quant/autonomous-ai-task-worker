"""Automated test suite for the Autonomous AI Task Worker.

Validates:
1. Natural language goal parsing & planning.
2. Tool execution (file search, extraction, master data, ingestion).
3. End-to-end autonomous completion:
   "Find the latest invoice from Company Acme, extract the amount and due date,
    enter it into our internal system, and tell me once it is done."
4. Human approval requirement when encountering prompt-injection document.
5. Indepedent outcome verification confirming record persistence in SQLite.
6. Worker API endpoints and live SSE event stream.
"""

import shutil
import hashlib
from pathlib import Path

from starlette.testclient import TestClient

from app import config
from app.api import app
from app.worker.agent import AutonomousWorker
from app.worker import tools


def _stage_upload(filename: str) -> None:
    """Copy a synthetic test PDF into the worker's allowed upload area."""
    source = config.FIXTURE_INVOICE_DIR / filename
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, config.UPLOAD_DIR / filename)


def test_worker_end_to_end_natural_language_task():
    """Validates the exact prompt from the user problem description."""
    _stage_upload("INV-2026-0847_acme.pdf")
    task = "Find the latest invoice from Company Acme, extract the amount and due date, enter it into our internal system, and tell me once it is done."
    worker = AutonomousWorker(task)

    # 1. Goal understanding
    assert worker.memory.target_company == "Acme"
    plan = worker.generate_plan()
    assert len(plan) >= 4
    assert any("Record" in step for step in plan)

    # 2. Autonomous execution
    events = list(worker.execute())
    event_types = [e["type"] for e in events]

    assert "started" in event_types
    assert "plan" in event_types
    assert "step" in event_types
    assert "observation" in event_types
    assert "completed" in event_types

    # 3. Final event has evidence and verification
    final_event = next(e for e in events if e["type"] == "completed")
    summary = final_event["summary"]
    evidence = final_event["evidence"]

    assert "Acme" in summary
    assert evidence["invoice_number"] is not None
    assert evidence["amount"] is not None
    assert evidence["internal_run_id"] is not None
    assert evidence["verification_status"] == "RECORDED_AND_VERIFIED"
    assert evidence["payment_approved"] is True
    assert evidence["verified_record"]["verified"] is True


def test_worker_safety_pause_on_prompt_injection():
    """Worker detects injection attempt and pauses for human approval instead of blind approval."""
    _stage_upload("INV-2026-1099_acme_injection.pdf")
    task = "Process invoice INV-2026-1099 from Acme and enter it into the internal system."
    worker = AutonomousWorker(task)

    events = list(worker.execute())
    approval_event = next((e for e in events if e["type"] == "approval_required"), None)

    assert approval_event is not None
    assert approval_event["policy"] == "R0_prompt_injection_detected"
    assert "prompt injection" in approval_event["message"].lower()

    # Now simulate human approval to resume
    resume_events = list(worker.execute(human_approval=True))
    completed_event = next((e for e in resume_events if e["type"] == "completed"), None)
    assert completed_event is not None
    assert completed_event["evidence"]["internal_run_id"] is not None


def test_worker_api_endpoints():
    """Tests the /api/worker/task endpoint and streaming."""
    _stage_upload("INV-2026-0847_acme.pdf")
    with TestClient(app) as client:
        # Create task
        res = client.post(
            "/api/worker/task",
            json={"task": "Find the latest invoice from Acme and enter it into our system."},
        )
        assert res.status_code == 200
        data = res.json()
        assert "task_id" in data
        task_id = data["task_id"]

        # Stream task events
        stream_res = client.get(f"/api/worker/tasks/{task_id}/stream")
        assert stream_res.status_code == 200
        text = stream_res.text
        assert "data: " in text
        assert "completed" in text
        assert "RECORDED_AND_VERIFIED" in text

        # Check list endpoint
        list_res = client.get("/api/worker/tasks")
        assert list_res.status_code == 200
        tasks = list_res.json()
        assert any(t["id"] == task_id for t in tasks)


def test_worker_api_approval_resumes_review_task_and_persists_history():
    """Review pauses before recording, then explicit approval records and verifies the invoice."""
    _stage_upload("INV-2026-1099_acme_injection.pdf")
    with TestClient(app) as client:
        created = client.post(
            "/api/worker/task",
            json={"task": "Process invoice INV-2026-1099 from Acme and record it."},
        ).json()
        task_id = created["task_id"]

        stream = client.get(f"/api/worker/tasks/{task_id}/stream")
        assert "approval_required" in stream.text
        paused = client.get(f"/api/worker/tasks/{task_id}").json()
        assert paused["status"] == "awaiting_approval"
        assert paused["approval_needed"] is True

        resumed = client.post(f"/api/worker/tasks/{task_id}/approve", json={"approved": True})
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "completed"
        assert resumed.json()["result"]["evidence"]["payment_approved"] is False

        persisted = client.get(f"/api/worker/tasks/{task_id}").json()
        assert persisted["status"] == "completed"
        assert any(event["type"] == "human_approval" for event in persisted["events"])
        assert persisted["result"]["evidence"]["verification_status"] == "RECORDED_AND_VERIFIED"


def test_worker_never_searches_repository_fixtures():
    """Only explicitly uploaded documents are in the live worker's search scope."""
    assert tools.find_files("Acme") == []


def test_worker_parses_vendor_after_definite_article():
    worker = AutonomousWorker("Find the latest invoice from the ACME. Extract the amount due and date.")

    assert worker.memory.target_company == "ACME"
    assert "ACME" in worker.generate_plan()[0]


def test_worker_handles_unextracted_amount_without_crashing(monkeypatch, tmp_path):
    """A missing total should result in review, not a None formatting exception."""
    test_pdf = tmp_path / "invoice.pdf"
    test_pdf.write_bytes(b"%PDF-test")
    monkeypatch.setattr(tools, "find_files", lambda _query: [{
        "path": str(test_pdf), "filename": "invoice.pdf", "size_bytes": 100,
        "modified_time": "2026-10-09T00:00:00+00:00", "score": 1,
    }])
    monkeypatch.setattr(tools, "execute_pipeline", lambda _path: {
        "invoice_number": "INV-1", "vendor_name": "Acme", "invoice_date": "2026-10-01",
        "due_date": None, "total": None, "guardrails_flagged": False,
        "decision": "needs_review", "primary_reason": "total missing",
    })

    events = list(AutonomousWorker("Process the latest invoice from Acme and record it.").execute())

    observation = next(event for event in events if event.get("tool") == "execute_pipeline")
    assert "Amount: not extracted" in observation["thought"]
    assert any(event["type"] == "approval_required" for event in events)


def test_worker_stops_before_ingestion_when_rules_reject_duplicate():
    """A deterministic duplicate rejection is a hard stop before a second write."""
    original = config.FIXTURE_INVOICE_DIR / "INV-2026-0847_acme.pdf"
    prior = tools.ingest_into_internal_system(original)
    assert prior["success"] is True

    _stage_upload("INV-2026-0847_acme_resubmitted.pdf")
    worker = AutonomousWorker("Process invoice INV-2026-0847 from Acme and record it.")
    events = list(worker.execute())

    assert any(event["type"] == "blocked" for event in events)
    assert not any(
        event.get("action") == "ingest_into_internal_system"
        for event in events if event["type"] == "step"
    )


def test_worker_extract_only_request_does_not_write_to_ledger():
    _stage_upload("INV-2026-0847_acme.pdf")
    task = "Find the latest invoice from Acme and extract its amount and due date."
    events = list(AutonomousWorker(task).execute())

    completed = next(event for event in events if event["type"] == "completed")
    plan = next(event for event in events if event["type"] == "plan")
    assert "without changing the accounting ledger" in plan["thought"]
    assert completed["evidence"]["recorded"] is False
    assert not any(event.get("action") == "ingest_into_internal_system" for event in events)


def test_worker_summarize_this_uses_single_uploaded_invoice_without_recording():
    """Outcome-oriented summary requests need not repeat the word invoice."""
    _stage_upload("INV-8613_meridian.pdf")
    events = list(AutonomousWorker("Hey, can you summarize this?").execute())

    completed = next(event for event in events if event["type"] == "completed")
    assert completed["evidence"]["invoice_number"] == "INV-8613"
    assert completed["evidence"]["amount"] == 9168.25
    assert completed["evidence"]["recorded"] is False
    assert not any(event.get("action") == "ingest_into_internal_system" for event in events)


def test_worker_extract_and_record_information_supports_contextual_invoice_goal():
    _stage_upload("INV-8613_meridian.pdf")
    worker = AutonomousWorker("Extract the information, record it, and provide evidence.")

    assert worker._is_supported_invoice_goal()
    assert worker.memory.requested_action == "record"


def test_worker_clarifies_equally_relevant_invoice_candidates():
    source = config.FIXTURE_INVOICE_DIR / "INV-2026-0847_acme.pdf"
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, config.UPLOAD_DIR / "ACME_invoice_april.pdf")
    shutil.copyfile(source, config.UPLOAD_DIR / "ACME_invoice_may.pdf")
    events = list(AutonomousWorker("Process an invoice from Acme and record it.").execute())

    question = next(event for event in events if event["type"] == "clarification_required")
    assert "which one" in question["question"].lower()
    assert len(question["candidates"]) == 2
    assert all(candidate["sha256"] for candidate in question["candidates"])


def test_worker_rejects_selected_file_changed_after_clarification():
    source = config.FIXTURE_INVOICE_DIR / "INV-2026-0847_acme.pdf"
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, config.UPLOAD_DIR / "ACME_invoice_april.pdf")
    shutil.copyfile(source, config.UPLOAD_DIR / "ACME_invoice_may.pdf")
    files = tools.find_files("Acme")
    selected = files[0]
    old_hash = hashlib.sha256(Path(selected["path"]).read_bytes()).hexdigest()
    Path(selected["path"]).write_bytes(Path(selected["path"]).read_bytes() + b"\nchanged")

    events = list(AutonomousWorker("Process an invoice from Acme and record it.").execute(
        selected_file_path=selected["path"], expected_file_sha256=old_hash,
    ))

    failure = next(event for event in events if event["type"] == "failed")
    assert "changed after review" in failure["error"]


def test_worker_declines_unrelated_goals_without_invoice_actions():
    events = list(AutonomousWorker("Open the payroll app and send a payment.").execute())

    assert events[-1]["type"] == "unsupported"
    assert not any(event["type"] == "step" for event in events)


def test_worker_clarification_api_selects_a_candidate_and_resumes():
    _stage_upload("INV-2026-0847_acme.pdf")
    _stage_upload("INV-8613_meridian.pdf")
    with TestClient(app) as client:
        created = client.post(
            "/api/worker/task",
            json={"task": "Process an invoice and record it."},
        ).json()
        task_id = created["task_id"]
        streamed = client.get(f"/api/worker/tasks/{task_id}/stream")
        assert "clarification_required" in streamed.text

        task = client.get(f"/api/worker/tasks/{task_id}").json()
        assert task["status"] == "awaiting_clarification"
        choices = next(event for event in task["events"] if event["type"] == "clarification_required")
        response = client.post(
            f"/api/worker/tasks/{task_id}/clarify",
            json={"candidate_id": choices["candidates"][0]["candidate_id"]},
        )

        assert response.status_code == 200
        assert response.json()["status"] in {"completed", "awaiting_approval"}


def test_verification_does_not_claim_missing_expected_values_match(monkeypatch):
    monkeypatch.setattr(tools.db, "get_run", lambda _run_id: {
        "id": 55, "status": "completed", "decision": "needs_review",
        "invoice_number": "INV-55", "vendor_name": "Acme", "total": 100.0,
        "stored_path": "upload.pdf", "created_at": "now",
        "trace": {"extract": {"fields": {"due_date": {"value": None}}}},
    })

    result = tools.verify_outcome(
        run_id=55,
        expected={"invoice_number": "INV-55", "vendor_name": "Acme", "total": 100.0, "due_date": None},
    )

    assert result["recorded"] is True
    assert result["verified"] is False
    assert result["unverified_fields"] == ["due_date"]


def test_blocked_task_exposes_reason_and_can_be_cancelled():
    with TestClient(app) as client:
        created = client.post(
            "/api/worker/task", json={"task": "Process an invoice and record it."},
        ).json()
        task_id = created["task_id"]
        from app import db
        db.update_worker_task(
            task_id, status="blocked", approval_needed=False,
            events=[{"type": "blocked", "reason": "duplicate invoice"}],
            result={"type": "blocked", "reason": "duplicate invoice"},
        )

        public = client.get(f"/api/worker/tasks/{task_id}").json()
        assert public["blocked_reason"] == "duplicate invoice"
        assert public["next_action"] == "cancel"
        cancelled = client.post(f"/api/worker/tasks/{task_id}/cancel")
        assert cancelled.json()["status"] == "cancelled"
        assert client.get(f"/api/worker/tasks/{task_id}").json()["status"] == "cancelled"
