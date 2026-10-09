import {
  ScanText,
  ShieldAlert,
  ShieldCheck,
  GitCompareArrows,
  Scale,
  CheckCircle2,
  Loader2,
  AlertTriangle,
  XCircle,
  Clock,
} from "lucide-react";
import type { StageState } from "@/hooks/use-run-stream";
import type { StageName } from "@/lib/types";
import { STAGE_ORDER } from "@/lib/types";
import { cn } from "@/lib/utils";

const STAGE_META: Record<
  StageName,
  { label: string; description: string; icon: typeof ScanText }
> = {
  extract: {
    label: "Extract",
    description: "PDF text layer / Groq vision parse",
    icon: ScanText,
  },
  guardrails: {
    label: "Guardrails",
    description: "Prompt injection & bounds scan",
    icon: ShieldAlert,
  },
  validate: {
    label: "Validate",
    description: "Arithmetic & required fields",
    icon: ShieldCheck,
  },
  match: {
    label: "Match",
    description: "Master vendor & PO tolerance",
    icon: GitCompareArrows,
  },
  decide: {
    label: "Decide",
    description: "Deterministic business rules",
    icon: Scale,
  },
};

function getStageSummary(name: StageName, output: Record<string, unknown> | undefined): string {
  if (!output) return "";
  try {
    switch (name) {
      case "extract": {
        const conf = output.extraction_confidence as number | undefined;
        const method = output.method === "vision" ? "Vision-LLM" : "Text-Native";
        return `${method} · ${conf != null ? Math.round(conf * 100) + "%" : ""}`;
      }
      case "guardrails": {
        const flagged = output.flagged as boolean | undefined;
        const findings = output.findings as unknown[] | undefined;
        return flagged ? `Flagged (${findings?.length ?? 0} hits)` : "Clean (0 hits)";
      }
      case "validate": {
        const passed = output.passed as boolean | undefined;
        return passed ? "Checks Passed" : "Check Failed";
      }
      case "match": {
        const vendor = (output.vendor_match as Record<string, unknown> | null)?.vendor_name;
        const po = (output.po_match as Record<string, unknown> | null)?.po_number;
        if (vendor && po) return `${vendor} · ${po}`;
        if (vendor) return `${vendor}`;
        return "No Vendor Match";
      }
      case "decide": {
        const decision = output.decision as string | undefined;
        if (decision === "auto_approve") return "Auto-Approved";
        if (decision === "needs_review") return "Needs Review";
        if (decision === "reject") return "Rejected";
        return decision || "";
      }
    }
  } catch {
    return "";
  }
}

interface ProcessingStatusAreaProps {
  stages: Record<StageName, StageState>;
  isProcessing: boolean;
  isComplete: boolean;
  failedError?: string | null;
  totalDurationMs?: number;
}

export function ProcessingStatusArea({
  stages,
  isProcessing,
  isComplete,
  failedError,
  totalDurationMs,
}: ProcessingStatusAreaProps) {
  return (
    <div className="space-y-3 rounded-2xl border border-border bg-card p-5 shadow-xs">
      <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-center">
        <div>
          <h3 className="font-display text-sm font-bold tracking-tight text-foreground">
            Pipeline Execution Flow
          </h3>
          <p className="text-xs text-muted-foreground">
            {isProcessing
              ? "Executing deterministic five-stage ingestion pipeline in real time…"
              : failedError
                ? "Pipeline execution failed."
                : isComplete
                  ? "All pipeline stages completed."
                  : "Awaiting execution."}
          </p>
        </div>
        {totalDurationMs != null && (
          <div className="flex items-center gap-1 font-mono text-xs text-muted-foreground">
            <Clock className="size-3.5" />
            <span>Total execution: {totalDurationMs} ms</span>
          </div>
        )}
      </div>

      {failedError && (
        <div className="flex items-center gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
          <XCircle className="size-4 shrink-0" />
          <span className="font-semibold">Pipeline Failure:</span>
          <span>{failedError}</span>
        </div>
      )}

      {/* 5-Stage visual flow */}
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 md:grid-cols-5">
        {STAGE_ORDER.map((name, index) => {
          const meta = STAGE_META[name];
          const state = stages[name];
          const Icon = meta.icon;
          const isRunning = state.status === "running";
          const isSuccess = state.status === "success";
          const isError = state.status === "error";
          const isFlagged =
            name === "guardrails" && isSuccess && Boolean(state.output?.flagged);
          const summary = getStageSummary(name, state.output);

          return (
            <div
              key={name}
              className={cn(
                "relative flex flex-col justify-between rounded-xl border p-3.5 transition-all duration-200",
                isRunning
                  ? "border-primary bg-primary/8 shadow-xs ring-2 ring-primary/20"
                  : isError
                    ? "border-destructive/50 bg-destructive/5"
                    : isFlagged
                      ? "border-amber-500/50 bg-amber-500/5"
                      : isSuccess
                        ? "border-emerald-500/30 bg-card hover:border-emerald-500/50"
                        : "border-border/70 bg-surface/40 opacity-70"
              )}
            >
              <div>
                <div className="flex items-center justify-between">
                  <div
                    className={cn(
                      "flex size-7 items-center justify-center rounded-lg text-xs",
                      isRunning
                        ? "bg-primary/20 text-primary"
                        : isError
                          ? "bg-destructive/20 text-destructive"
                          : isFlagged
                            ? "bg-amber-500/20 text-amber-600 dark:text-amber-400"
                            : isSuccess
                              ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400"
                              : "bg-surface text-muted-foreground"
                    )}
                  >
                    <Icon className="size-3.5" />
                  </div>

                  <span className="font-mono text-[10px] text-faint">
                    0{index + 1}
                  </span>
                </div>

                <div className="mt-2.5">
                  <span className="font-display text-xs font-bold text-foreground">
                    {meta.label}
                  </span>
                  <p className="mt-0.5 line-clamp-1 text-[10px] text-muted-foreground">
                    {meta.description}
                  </p>
                </div>
              </div>

              <div className="mt-3 border-t border-border/50 pt-2 text-[10px]">
                {isRunning ? (
                  <span className="inline-flex items-center gap-1 font-mono font-medium text-primary">
                    <Loader2 className="size-3 animate-spin" /> Running…
                  </span>
                ) : isError ? (
                  <span className="inline-flex items-center gap-1 font-mono font-medium text-destructive">
                    <XCircle className="size-3" /> Error
                  </span>
                ) : isFlagged ? (
                  <span className="inline-flex items-center gap-1 font-mono font-medium text-amber-600 dark:text-amber-400">
                    <AlertTriangle className="size-3" /> Flagged
                  </span>
                ) : isSuccess ? (
                  <div className="flex items-center justify-between gap-1 font-mono text-muted-foreground">
                    <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="size-3" />
                      <span className="truncate">{summary || "Done"}</span>
                    </span>
                    {state.durationMs != null && (
                      <span className="text-faint">{state.durationMs}ms</span>
                    )}
                  </div>
                ) : (
                  <span className="font-mono text-faint">Pending</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
