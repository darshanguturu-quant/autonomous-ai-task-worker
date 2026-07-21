/** Shapes mirrored from the FastAPI backend (app/db.py, app/pipeline/run.py). */

export type Decision = "auto_approve" | "needs_review" | "reject";
export type RunStatus = "running" | "completed" | "failed";
export type StageName = "extract" | "guardrails" | "validate" | "match" | "decide";

export const STAGE_ORDER: StageName[] = ["extract", "guardrails", "validate", "match", "decide"];

export interface RunSummary {
  id: number;
  created_at: string;
  filename: string;
  scenario: string | null;
  status: RunStatus;
  decision: Decision | null;
  invoice_number: string | null;
  vendor_name: string | null;
  invoice_date: string | null;
  po_ref: string | null;
  total: number | null;
  error: string | null;
}

/** Final pipeline result (stored as trace_json, streamed as `result`). */
export interface RunTrace {
  invoice: {
    invoice_number: string | null;
    vendor_name: string | null;
    invoice_date: string | null;
    po_ref: string | null;
    total: number | null;
  };
  extract: Record<string, unknown>;
  guardrails: Record<string, unknown> & { flagged: boolean };
  validate: Record<string, unknown>;
  match: Record<string, unknown>;
  decide: Record<string, unknown> & { decision: Decision; primary_reason?: string };
}

export interface RunDetail extends RunSummary {
  trace: RunTrace | null;
}

/** One SSE event from GET /api/runs/{id}/stream. */
export interface StreamEvent {
  stage: StageName | "pipeline";
  status: "running" | "completed" | "failed";
  output?: Record<string, unknown>;
  duration_ms?: number;
  total_duration_ms?: number;
  result?: RunTrace;
  error?: string;
  replay?: boolean;
}
