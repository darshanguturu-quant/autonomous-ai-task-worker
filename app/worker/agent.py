"""Autonomous AI Task Worker Core Engine.

Implements an autonomous agent capable of:
1. Understanding the user's end goal from natural language.
2. Breaking the request into a planned sequence of actions.
3. Using available tools (files, extraction, master data, internal ERP system).
4. Observing results of each action.
5. Deciding what to do next based on observations.
6. Remembering relevant information in execution memory.
7. Detecting errors and attempting alternatives / retries.
8. Verifying whether the requested outcome was actually achieved in the internal database.
9. Pausing for human approval when safety policies dictate (e.g. prompt injection, cap breach).
10. Returning a concise summary and evidence of completion.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
import hashlib
from typing import Any

from app.worker import tools

log = logging.getLogger("worker.agent")


def _display_amount(value: Any) -> str:
    """Render an extracted amount without assuming that extraction succeeded."""
    if value is None:
        return "not extracted"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "not extracted"


@dataclass
class AgentMemory:
    """Working memory that preserves discovered entities across execution steps."""
    goal: str = ""
    target_company: str | None = None
    target_invoice_number: str | None = None
    requested_action: str = "extract"
    asks_for_latest: bool = False
    discovered_files: list[dict[str, Any]] = field(default_factory=list)
    selected_file: dict[str, Any] | None = None
    extracted_data: dict[str, Any] = field(default_factory=dict)
    ingestion_result: dict[str, Any] = field(default_factory=dict)
    verification_result: dict[str, Any] = field(default_factory=dict)
    errors_encountered: list[str] = field(default_factory=list)
    human_approval_granted: bool = False


class AutonomousWorker:
    """Autonomous agent orchestrating multi-step task execution."""

    def __init__(self, task_description: str):
        self.task_description = task_description
        self.memory = AgentMemory(goal=task_description)
        self._parse_intent()

    def _parse_intent(self) -> None:
        """Understand the user's end goal and target entities from natural language."""
        text = self.task_description
        
        # Look for company / vendor name (e.g. "from Company X", "from Acme", "for Meridian")
        company_match = re.search(
            r"(?:from|for|by)\s+(?:(?:the|our)\s+)?(?:Company\s+)?"
            r"([A-Za-z0-9_-]+(?:\s+(?:Corp|LLC|Inc|Ltd|Company|Technologies|Supplies))?)",
            text,
            re.I,
        )
        if company_match:
            candidate = company_match.group(1).strip().rstrip(".,!?;:")
            # Clean common words
            if candidate.lower() not in {"our", "the", "an", "a", "all", "latest", "internal", "system"}:
                self.memory.target_company = candidate

        # Look for invoice number reference (e.g. "INV-2026-0847")
        inv_match = re.search(r"\b(INV-[A-Za-z0-9-]+)\b", text, re.I)
        if inv_match:
            self.memory.target_invoice_number = inv_match.group(1).upper()

        self.memory.asks_for_latest = bool(
            re.search(r"\b(latest|newest|most recent)\b", text, re.I)
        )
        self.memory.requested_action = (
            "record" if re.search(r"\b(record|enter|submit|book|ingest|save)\b", text, re.I)
            else "extract"
        )

    def _is_supported_invoice_goal(self) -> bool:
        """Accept invoice goals expressed by outcome, even if 'invoice' is omitted."""
        text = self.task_description
        explicit_invoice = re.search(r"\binvoice\b|\bINV-[A-Za-z0-9-]+\b", text, re.I)
        contextual_summary = re.search(
            r"\b(summar(?:y|ize|ise)|extract|read|review)\b.*\b(this|it|document|file|details|information)\b",
            text,
            re.I,
        )
        contextual_invoice_fields = re.search(
            r"\b(amount\s+due|due\s+date|invoice\s+fields|invoice\s+details)\b",
            text,
            re.I,
        )
        extract_and_record = (
            re.search(r"\b(extract|read|summar(?:y|ize|ise))\b", text, re.I)
            and re.search(r"\b(record|enter|submit|book|ingest|save)\b", text, re.I)
            and re.search(r"\b(information|details|data|it|this)\b", text, re.I)
        )
        return bool(explicit_invoice or contextual_summary or contextual_invoice_fields or extract_and_record)

    def generate_plan(self) -> list[str]:
        """Decompose the goal into a sequence of actionable steps."""
        company = self.memory.target_company or "specified vendor"
        plan = [f"1. Search uploaded documents for an invoice matching '{company}'"]
        plan.append("2. Extract requested invoice fields and run document safety/validation checks")
        if self.memory.requested_action == "record":
            plan.extend([
                "3. Check deterministic vendor/PO decision and request approval if required",
                "4. Record only if policy permits and independently verify the persisted invoice",
            ])
        else:
            plan.append("3. Report extracted fields and evidence without changing the accounting ledger")
        return plan

    def execute(
        self,
        human_approval: bool = False,
        selected_file_path: str | None = None,
        expected_file_sha256: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Execute the task autonomously, yielding streaming events for each action."""
        if human_approval:
            self.memory.human_approval_granted = True

        t_start = time.perf_counter()
        yield {
            "type": "started",
            "task": self.task_description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Only support the narrow invoice workflow; never reinterpret unrelated
        # requests as permission to process or record an invoice.
        if not self._is_supported_invoice_goal():
            yield {
                "type": "unsupported",
                "message": "This worker currently supports invoice search, extraction, and optional recording only. Please describe an invoice task.",
            }
            return

        # Step 1: Generate Plan
        plan = self.generate_plan()
        yield {
            "type": "plan",
            "steps": plan,
            "thought": (
                f"Understood objective: locate and summarize an uploaded invoice for "
                f"'{self.memory.target_company or 'the requested document'}' without changing the accounting ledger."
                if self.memory.requested_action == "extract" else
                f"Understood objective: locate invoice for '{self.memory.target_company or 'target'}', "
                "extract financial fields, record only if policy permits, and verify the outcome."
            ),
        }

        # Step 2: File Search with autonomous retry / alternative strategies
        yield {
            "type": "step",
            "step_index": 0,
            "action": "find_files",
            "description": f"Searching filesystem for matching invoice files (Query: '{self.memory.target_company or 'invoice'}').",
        }

        search_query = self.memory.target_invoice_number or self.memory.target_company or "invoice"
        files = tools.find_files(search_query)

        # Retry strategy if initial query found nothing
        if not files and self.memory.target_company:
            yield {
                "type": "retry",
                "reason": f"No files matched specific query '{search_query}'. Attempting alternative search with broad query 'invoice'.",
            }
            files = tools.find_files("invoice")

        if not files:
            yield {
                "type": "failed",
                "error": f"Could not find any invoice matching '{self.task_description}' in accessible storage locations.",
            }
            return

        # Resolve a user-selected candidate only from the current safe search
        # results, and bind any later approval to the exact file contents.
        if selected_file_path:
            selected_resolved = Path(selected_file_path).resolve()
            safe_root = tools.config.UPLOAD_DIR.resolve()
            try:
                selected_resolved.relative_to(safe_root)
            except ValueError:
                yield {"type": "failed", "error": "Selected invoice is outside the permitted uploads folder."}
                return
            chosen = next((item for item in files if Path(item["path"]).resolve() == selected_resolved), None)
            if chosen is None or not selected_resolved.is_file():
                yield {"type": "failed", "error": "Selected invoice is no longer available in the current search results."}
                return
            current_digest = hashlib.sha256(selected_resolved.read_bytes()).hexdigest()
            if expected_file_sha256 and current_digest != expected_file_sha256:
                yield {"type": "failed", "error": "Selected invoice changed after review; please review the current file again."}
                return
            files = [chosen]
        elif len(files) > 1 and not self.memory.asks_for_latest and not self.memory.target_invoice_number:
            top_score = files[0]["score"]
            ambiguous = [item for item in files if item["score"] == top_score]
            if len(ambiguous) > 1:
                options = []
                for index, item in enumerate(ambiguous):
                    digest = hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
                    options.append({
                        "candidate_id": index,
                        "filename": item["filename"],
                        "modified_time": item["modified_time"],
                        "path": item["path"],
                        "sha256": digest,
                    })
                yield {
                    "type": "clarification_required",
                    "question": "Several equally relevant invoices match. Which one should I process?",
                    "candidates": options,
                }
                return

        self.memory.discovered_files = files
        selected_file = files[0]
        self.memory.selected_file = selected_file

        yield {
            "type": "observation",
            "tool": "find_files",
            "result": {
                "total_matches": len(files),
                "selected_file": selected_file["filename"],
                "path": selected_file["path"],
                "modified": selected_file["modified_time"],
                "sha256": hashlib.sha256(Path(selected_file["path"]).read_bytes()).hexdigest(),
            },
            "thought": f"Located candidate document '{selected_file['filename']}' ({selected_file['size_bytes']} bytes). Proceeding to inspection and pipeline processing.",
        }

        # Step 3: Run Document Pipeline & Field Extraction
        yield {
            "type": "step",
            "step_index": 1,
            "action": "execute_pipeline",
            "description": f"Executing 5-stage pipeline on '{selected_file['filename']}' to extract amounts, due dates, and run guardrails.",
        }

        pipe_res = tools.execute_pipeline(selected_file["path"])
        if "error" in pipe_res:
            yield {
                "type": "failed",
                "error": f"Extraction pipeline failed: {pipe_res['error']}",
            }
            return

        self.memory.extracted_data = pipe_res
        yield {
            "type": "observation",
            "tool": "execute_pipeline",
            "result": {
                "invoice_number": pipe_res.get("invoice_number"),
                "vendor_name": pipe_res.get("vendor_name"),
                "invoice_date": pipe_res.get("invoice_date"),
                "due_date": pipe_res.get("due_date"),
                "total": pipe_res.get("total"),
                "guardrails_flagged": pipe_res.get("guardrails_flagged"),
                "decision": pipe_res.get("decision"),
            },
            "thought": (
                f"Extracted Invoice #{pipe_res.get('invoice_number')} from {pipe_res.get('vendor_name')}. "
                f"Amount: {_display_amount(pipe_res.get('total'))}, "
                f"Due Date: {pipe_res.get('due_date') or 'Omitted on doc'}."
            ),
        }

        if self.memory.requested_action == "extract":
            yield {
                "type": "completed",
                "summary": (
                    f"Found invoice {pipe_res.get('invoice_number') or '(number not extracted)'} from "
                    f"{pipe_res.get('vendor_name') or '(vendor not extracted)'}. "
                    f"Amount due: {_display_amount(pipe_res.get('total'))}; "
                    f"due date: {pipe_res.get('due_date') or 'not found'}. "
                    "No accounting record was changed because recording was not requested."
                ),
                "evidence": {
                    "file_processed": selected_file["filename"],
                    "invoice_number": pipe_res.get("invoice_number"),
                    "vendor_name": pipe_res.get("vendor_name"),
                    "amount": pipe_res.get("total"),
                    "due_date": pipe_res.get("due_date"),
                    "decision": pipe_res.get("decision"),
                    "recorded": False,
                },
            }
            return

        # Reject decisions are hard stops. A human may approve recording a
        # review case, but cannot use this workflow to override a deterministic
        # rejection.
        decision = pipe_res.get("decision")
        if decision == "reject":
            yield {
                "type": "blocked",
                "reason": pipe_res.get("primary_reason") or "Deterministic rules rejected this invoice.",
                "message": "The invoice was not entered because the rules engine rejected it.",
                "invoice_data": {
                    "invoice_number": pipe_res.get("invoice_number"),
                    "vendor": pipe_res.get("vendor_name"),
                    "total": pipe_res.get("total"),
                    "decision": decision,
                },
            }
            return

        # Safety policy: suspected prompt injection and any non-auto-approved
        # invoice require an explicit human decision before recording.
        approval_reason = (
            "R0_prompt_injection_detected" if pipe_res.get("guardrails_flagged")
            else "invoice_requires_review" if decision == "needs_review"
            else None
        )
        if approval_reason and not self.memory.human_approval_granted:
            yield {
                "type": "approval_required",
                "policy": approval_reason,
                "message": (
                    f"Suspicious prompt injection text was detected in '{selected_file['filename']}'. "
                    "Review the document before allowing it to be recorded."
                    if pipe_res.get("guardrails_flagged") else
                    f"The rules engine returned needs_review for '{selected_file['filename']}'. "
                    "Review the extracted evidence before allowing it to be recorded."
                ),
                "invoice_data": {
                    "invoice_number": pipe_res.get("invoice_number"),
                    "vendor": pipe_res.get("vendor_name"),
                    "total": pipe_res.get("total"),
                    "decision": decision,
                    "reason": pipe_res.get("primary_reason"),
                },
            }
            return

        # Step 5: Ingest into Internal System
        yield {
            "type": "step",
            "step_index": 2,
            "action": "ingest_into_internal_system",
            "description": f"Submitting invoice #{pipe_res.get('invoice_number')} into internal accounting system.",
        }

        ingest_res = tools.ingest_into_internal_system(selected_file["path"])
        if not ingest_res.get("success"):
            yield {
                "type": "failed",
                "error": f"Internal system ingestion failed: {ingest_res.get('error')}",
            }
            return

        self.memory.ingestion_result = ingest_res
        run_id = ingest_res["run_id"]

        yield {
            "type": "observation",
            "tool": "ingest_into_internal_system",
            "result": ingest_res,
            "thought": f"Invoice successfully booked in internal system with Run #{run_id}. System decision: {ingest_res.get('decision')}.",
        }

        # Step 6: Explicit Outcome Verification
        yield {
            "type": "step",
            "step_index": 3,
            "action": "verify_outcome",
            "description": f"Verifying whether Run #{run_id} is permanently recorded in the internal SQLite database.",
        }

        verify_res = tools.verify_outcome(
            run_id=run_id,
            expected={
                "invoice_number": pipe_res.get("invoice_number"),
                "vendor_name": pipe_res.get("vendor_name"),
                "total": pipe_res.get("total"),
                "due_date": pipe_res.get("due_date"),
            },
        )
        self.memory.verification_result = verify_res

        if not verify_res.get("verified"):
            yield {
                "type": "failed",
                "error": f"Verification check failed: Record was not confirmed in database. ({verify_res.get('reason')})",
            }
            return

        yield {
            "type": "observation",
            "tool": "verify_outcome",
            "result": verify_res,
            "thought": (
                "Verified that the invoice record is persisted and auto-approved."
                if verify_res.get("approved") else
                "Verified that the invoice is persisted as a review item; it has not been approved for payment."
            ),
        }

        # Step 7: Final Completion Summary with Evidence Trail
        total_time_ms = int((time.perf_counter() - t_start) * 1000)
        is_approved = verify_res.get("approved", False)
        decision_summary = (
            "approved by deterministic policy" if is_approved
            else "recorded for human review; not approved for payment"
        )
        yield {
            "type": "completed",
            "summary": (
                f"Recorded invoice {pipe_res.get('invoice_number')} "
                f"from {pipe_res.get('vendor_name')} in the internal system ({decision_summary}). "
                f"Extracted Amount: {_display_amount(pipe_res.get('total'))}, Due Date: {pipe_res.get('due_date') or 'Not specified on document'}. "
                f"Internal System Run ID: #{run_id} (Decision: {ingest_res.get('decision')}). "
                f"Database persistence independently verified."
            ),
            "evidence": {
                "file_processed": selected_file["filename"],
                "file_path": selected_file["path"],
                "invoice_number": pipe_res.get("invoice_number"),
                "vendor_name": pipe_res.get("vendor_name"),
                "amount": pipe_res.get("total"),
                "due_date": pipe_res.get("due_date"),
                "internal_run_id": run_id,
                "system_decision": ingest_res.get("decision"),
                "verification_status": "RECORDED_AND_VERIFIED" if verify_res.get("recorded") else "NOT_VERIFIED",
                "payment_approved": is_approved,
                "verified_record": verify_res,
                "execution_duration_ms": total_time_ms,
            },
        }
