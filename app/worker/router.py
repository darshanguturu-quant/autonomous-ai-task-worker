"""API router for durable Autonomous AI Task Worker tasks."""

import json
import threading
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import db
from app.worker.agent import AutonomousWorker

router = APIRouter(prefix="/api/worker", tags=["worker"])
_active_tasks: set[str] = set()
_tasks_lock = threading.Lock()
_TERMINAL_STATUSES = {"completed", "failed", "blocked", "rejected_by_user", "unsupported", "cancelled"}


class TaskRequest(BaseModel):
    task: str = Field(min_length=5, max_length=2000)


class ApprovalResponse(BaseModel):
    approved: bool


class ClarificationResponse(BaseModel):
    candidate_id: int = Field(ge=0)


def _load_task(task_id: str) -> dict[str, Any]:
    task = db.get_worker_task(task_id)
    if not task:
        raise HTTPException(404, f"Task {task_id} not found")
    return task


def _save_task(task: dict[str, Any]) -> None:
    db.update_worker_task(
        task["id"], status=task["status"], events=task["events"],
        approval_needed=task["approval_needed"], result=task["result"],
    )


def _public_task(task: dict[str, Any], *, include_events: bool = False) -> dict[str, Any]:
    fields = {key: task[key] for key in ("id", "task", "created_at", "status", "approval_needed")}
    if task["status"] == "blocked":
        result = task.get("result") or {}
        blocked_event = next(
            (event for event in reversed(task.get("events", [])) if event.get("type") == "blocked"),
            {},
        )
        fields["blocked_reason"] = (
            result.get("reason") or result.get("message") or result.get("error")
            or blocked_event.get("reason") or blocked_event.get("message")
            or "This task was blocked before a reason was saved. Cancel it and submit a corrected task."
        )
        fields["next_action"] = "cancel"
        fields["next_action_label"] = "Cancel blocked task"
    if include_events:
        fields.update(events=task["events"], result=task["result"])
    return fields


@router.post("/task")
def create_worker_task(req: TaskRequest):
    """Create a durable task from a natural-language request."""
    task_id = str(uuid.uuid4())
    db.create_worker_task(task_id, req.task.strip())
    return {"task_id": task_id, "status": "pending", "task": req.task.strip()}


@router.get("/tasks")
def list_worker_tasks():
    """List persisted worker tasks, newest first."""
    return [_public_task(task) for task in db.list_worker_tasks()]


@router.get("/tasks/{task_id}")
def get_worker_task(task_id: str):
    return _public_task(_load_task(task_id), include_events=True)


@router.post("/tasks/{task_id}/approve")
def approve_worker_task(task_id: str, resp: ApprovalResponse):
    """Approve a review checkpoint or reject the proposed continuation."""
    with _tasks_lock:
        task = _load_task(task_id)
        if task["status"] != "awaiting_approval" or not task["approval_needed"]:
            return {"status": task["status"], "message": "Task is not waiting for approval"}
        if task_id in _active_tasks:
            raise HTTPException(409, "Task is already executing")
        _active_tasks.add(task_id)

    try:
        if not resp.approved:
            result = {"type": "rejected_by_user", "message": "Human reviewer declined the requested action."}
            task["status"] = "rejected_by_user"
            task["approval_needed"] = False
            task["result"] = result
            task["events"].append(result)
            _save_task(task)
            return {"status": task["status"], "result": result}

        task["approval_needed"] = False
        task["events"].append({"type": "human_approval", "approved": True})
        task["status"] = "running"
        _save_task(task)

        # Re-evaluate from the beginning against the exact file and hash shown
        # at the approval checkpoint; never let a changed search result inherit
        # the user's previous approval.
        prior_observation = next(
            (event for event in reversed(task["events"])
             if event.get("type") == "observation" and event.get("tool") == "find_files"),
            None,
        )
        selected = (prior_observation or {}).get("result", {})
        if not selected.get("path") or not selected.get("sha256"):
            task["status"] = "failed"
            task["result"] = {"type": "failed", "error": "Approval checkpoint has no pinned invoice evidence; start a new task."}
            task["events"].append(task["result"])
            _save_task(task)
            return {"status": task["status"], "result": task["result"]}

        worker = AutonomousWorker(task["task"])
        continuation_started = False
        for event in worker.execute(
            human_approval=True,
            selected_file_path=selected["path"],
            expected_file_sha256=selected["sha256"],
        ):
            if not continuation_started:
                continuation_started = (
                    (event.get("type") == "step" and event.get("action") == "ingest_into_internal_system")
                    or event.get("type") in {"failed", "blocked"}
                )
                if not continuation_started:
                    continue
            task["events"].append(event)
            if event["type"] == "completed":
                task["status"] = "completed"
                task["result"] = event
            elif event["type"] in {"failed", "blocked", "unsupported"}:
                task["status"] = "failed" if event["type"] == "failed" else event["type"]
                task["result"] = event
            _save_task(task)

        if task["status"] == "running":
            task["status"] = "failed"
            task["result"] = {"type": "failed", "error": "Task ended without a terminal event."}
            task["events"].append(task["result"])
            _save_task(task)
        return {"status": task["status"], "result": task["result"]}
    finally:
        with _tasks_lock:
            _active_tasks.discard(task_id)


@router.post("/tasks/{task_id}/cancel")
def cancel_worker_task(task_id: str):
    """Close a blocked or waiting task when its requested action cannot proceed."""
    with _tasks_lock:
        task = _load_task(task_id)
        if task["status"] not in {"blocked", "failed", "awaiting_approval", "awaiting_clarification", "pending"}:
            return {"status": task["status"], "message": "Task is not in a cancellable state"}
        if task_id in _active_tasks:
            raise HTTPException(409, "Task is currently executing and cannot be cancelled")
        result = {
            "type": "cancelled",
            "message": "Task cancelled by user. No further action will be attempted.",
        }
        task["status"] = "cancelled"
        task["approval_needed"] = False
        task["result"] = result
        task["events"].append(result)
        _save_task(task)
    return {"status": "cancelled", "result": result}


@router.post("/tasks/{task_id}/clarify")
def clarify_worker_task(task_id: str, resp: ClarificationResponse):
    """Resume an ambiguous search using one candidate shown to the user."""
    with _tasks_lock:
        task = _load_task(task_id)
        if task["status"] != "awaiting_clarification":
            return {"status": task["status"], "message": "Task is not waiting for clarification"}
        if task_id in _active_tasks:
            raise HTTPException(409, "Task is already executing")
        clarification = next(
            (event for event in reversed(task["events"])
             if event.get("type") == "clarification_required"),
            None,
        )
        candidates = (clarification or {}).get("candidates", [])
        selected = next(
            (item for item in candidates if item.get("candidate_id") == resp.candidate_id),
            None,
        )
        if selected is None:
            raise HTTPException(400, "That invoice choice is not available in this clarification request")
        _active_tasks.add(task_id)

    try:
        task["status"] = "running"
        task["events"].append({
            "type": "human_clarification",
            "candidate_id": selected["candidate_id"],
            "filename": selected["filename"],
        })
        _save_task(task)
        worker = AutonomousWorker(task["task"])
        for event in worker.execute(
            selected_file_path=selected["path"],
            expected_file_sha256=selected["sha256"],
        ):
            task["events"].append(event)
            if event["type"] == "approval_required":
                task["status"] = "awaiting_approval"
                task["approval_needed"] = True
            elif event["type"] == "clarification_required":
                task["status"] = "awaiting_clarification"
            elif event["type"] in {"completed", "failed", "blocked", "unsupported"}:
                task["status"] = "failed" if event["type"] == "failed" else event["type"]
                task["result"] = event
            else:
                task["status"] = "running"
            _save_task(task)
        if task["status"] == "running":
            task["status"] = "failed"
            task["result"] = {"type": "failed", "error": "Task ended without a terminal event."}
            task["events"].append(task["result"])
            _save_task(task)
        return {"status": task["status"], "result": task["result"]}
    finally:
        with _tasks_lock:
            _active_tasks.discard(task_id)


@router.get("/tasks/{task_id}/stream")
def stream_worker_task(task_id: str):
    """Stream execution events; terminal tasks are replayed from SQLite."""
    task = _load_task(task_id)

    def event_generator():
        nonlocal task
        if task["status"] in _TERMINAL_STATUSES or task["status"] in {"awaiting_approval", "awaiting_clarification"}:
            for event in task["events"]:
                yield f"data: {json.dumps(event)}\n\n"
            return

        with _tasks_lock:
            if task_id in _active_tasks:
                yield f"data: {json.dumps({'type': 'failed', 'error': 'Task is already executing.'})}\n\n"
                return
            _active_tasks.add(task_id)

        task["status"] = "running"
        _save_task(task)
        try:
            worker = AutonomousWorker(task["task"])
            for event in worker.execute():
                task["events"].append(event)
                if event["type"] == "approval_required":
                    task["status"] = "awaiting_approval"
                    task["approval_needed"] = True
                elif event["type"] == "clarification_required":
                    task["status"] = "awaiting_clarification"
                elif event["type"] == "completed":
                    task["status"] = "completed"
                    task["result"] = event
                elif event["type"] in {"failed", "blocked", "unsupported"}:
                    task["status"] = "failed" if event["type"] == "failed" else event["type"]
                    task["result"] = event
                _save_task(task)
                yield f"data: {json.dumps(event)}\n\n"
                if task["status"] != "running":
                    return
        except Exception as exc:
            task["status"] = "failed"
            task["result"] = {"type": "failed", "error": f"Worker execution error: {exc}"}
            task["events"].append(task["result"])
            _save_task(task)
            yield f"data: {json.dumps(task['result'])}\n\n"
        finally:
            with _tasks_lock:
                _active_tasks.discard(task_id)

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )