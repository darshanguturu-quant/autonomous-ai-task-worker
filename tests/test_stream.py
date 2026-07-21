"""SSE live-stream tests: deferred runs execute while streaming; finished runs replay."""

import json

from fastapi.testclient import TestClient

from app.api import app
from tests.helpers import upload_fixture


def _events(client, run_id):
    events = []
    with client.stream("GET", f"/api/runs/{run_id}/stream") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def test_deferred_run_executes_live_on_stream():
    with TestClient(app) as c:
        created = upload_fixture(c, "INV-2026-0847_acme.pdf", defer=True)
        assert created["status"] == "pending"
        run_id = created["run_id"]

        # not executed yet
        assert c.get(f"/api/runs/{run_id}").json()["status"] == "running"

        events = _events(c, run_id)
        statuses = [(e["stage"], e["status"]) for e in events]
        assert statuses == [
            ("extract", "running"), ("extract", "completed"),
            ("guardrails", "running"), ("guardrails", "completed"),
            ("validate", "running"), ("validate", "completed"),
            ("match", "running"), ("match", "completed"),
            ("decide", "running"), ("decide", "completed"),
            ("pipeline", "completed"),
        ]
        # completed events are real executions with measured durations + outputs
        completed = [e for e in events if e["status"] == "completed" and e["stage"] != "pipeline"]
        assert all("duration_ms" in e and "output" in e for e in completed)
        assert not any(e.get("replay") for e in events)
        assert events[-1]["result"]["decide"]["decision"] == "auto_approve"

        # stream execution persisted the run
        run = c.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "completed" and run["decision"] == "auto_approve"


def test_finished_run_stream_replays_stored_trace():
    with TestClient(app) as c:
        run_id = upload_fixture(c, "INV-8613_meridian.pdf")["run_id"]
        events = _events(c, run_id)
        assert all(e.get("replay") for e in events)
        assert [e["stage"] for e in events] == \
            ["extract", "guardrails", "validate", "match", "decide", "pipeline"]
        assert events[-1]["result"]["decide"]["decision"] == "auto_approve"


def test_bad_upload_is_rejected_before_a_run_is_ever_created():
    # GUARDRAIL 1 (file validation) rejects this at the upload boundary, so
    # there is no run to stream at all - not a failed run, no run.
    with TestClient(app) as c:
        r = c.post("/api/invoices?defer=1",
                   files={"file": ("broken.pdf", b"not a real pdf", "application/pdf")})
        assert r.status_code == 400
        assert c.get("/api/runs").json() == []


def test_failed_run_stream_replays_error():
    # Bytes that clear the file-validation guardrail (real %PDF- header,
    # non-empty, under the size cap) but are still an unreadable PDF body -
    # this fails downstream, inside extraction, regardless of API-key config.
    corrupt_pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nthis is not a valid pdf body at all\n%%EOF"
    with TestClient(app) as c:
        created = c.post("/api/invoices?defer=1",
                         files={"file": ("broken.pdf", corrupt_pdf,
                                         "application/pdf")}).json()
        run_id = created["run_id"]

        live = _events(c, run_id)  # executes: pipeline fails on unreadable PDF
        assert live[-1]["stage"] == "pipeline" and live[-1]["status"] == "failed"
        assert live[-1]["error"]

        replay = _events(c, run_id)  # reopening replays the stored error
        assert replay == [{
            "stage": "pipeline", "status": "failed",
            "error": live[-1]["error"], "replay": True,
        }]
