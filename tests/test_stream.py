"""SSE tests: deferred runs execute on the queue; streams tail or replay persisted events."""

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

        # The background queue may start as soon as the upload is accepted.
        assert c.get(f"/api/runs/{run_id}").json()["status"] in {"running", "completed"}

        events = _events(c, run_id)
        statuses = [(e["stage"], e["status"]) for e in events]
        if events[0].get("replay"):
            assert statuses == [
                ("extract", "completed"), ("guardrails", "completed"),
                ("validate", "completed"), ("match", "completed"),
                ("decide", "completed"), ("pipeline", "completed"),
            ]
        else:
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
        assert all("output" in e for e in completed)
        assert all("duration_ms" in e for e in completed if not e.get("replay"))
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
        assert replay[-1] == {
            "stage": "pipeline", "status": "failed",
            "error": live[-1]["error"], "replay": True,
        }


def test_deferred_upload_queue_drains_multiple_files_to_terminal_state():
    import time

    filenames = [
        "INV-2026-1099_acme_injection.pdf",
        "INV-0092_vertex_no_po.pdf",
        "INV-8613_meridian.pdf",
    ]
    with TestClient(app) as client:
        run_ids = [upload_fixture(client, name, defer=True)["run_id"] for name in filenames]
        deadline = time.monotonic() + 15
        runs = []
        while time.monotonic() < deadline:
            runs = [client.get(f"/api/runs/{run_id}").json() for run_id in run_ids]
            if all(run["status"] in {"completed", "failed"} for run in runs):
                break
            time.sleep(0.05)

        assert len(runs) == 3
        assert all(run["status"] in {"completed", "failed"} for run in runs)
        for run in runs:
            if run["status"] == "failed":
                assert run["error"]
                assert run["trace"]
            else:
                assert run["decision"]
                assert run["trace"]


def test_extraction_timeout_marks_failed_with_error_and_trace(monkeypatch, tmp_path):
    import time
    import app.pipeline.run as pipeline_run

    def slow_extraction(_path):
        time.sleep(0.1)
        return {}

    monkeypatch.setattr(pipeline_run, "extract_invoice", slow_extraction)
    monkeypatch.setattr(pipeline_run, "EXTRACTION_TIMEOUT_SECONDS", 0.01)
    with TestClient(app) as client:
        corrupt_pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nthis is valid for upload\n%%EOF"
        response = client.post(
            "/api/invoices",
            files={"file": ("slow.pdf", corrupt_pdf, "application/pdf")},
        )
        assert response.status_code == 200
        run = client.get(f"/api/runs/{response.json()['run_id']}").json()
        assert run["status"] == "failed"
        assert "timeout" in run["error"].lower()
        assert run["trace"]


def test_stale_running_run_is_marked_failed_with_trace():
    from datetime import datetime, timedelta, timezone
    from app import db

    with TestClient(app) as client:
        run_id = db.create_run("stale.pdf", "stale.pdf")
        stale_date = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        with db._connect() as con:
            con.execute("UPDATE runs SET created_at=? WHERE id=?", (stale_date, run_id))

        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "failed"
        assert "stale-run guard" in run["error"].lower()
        assert run["trace"]
        assert _events(client, run_id)[-1]["status"] == "failed"
