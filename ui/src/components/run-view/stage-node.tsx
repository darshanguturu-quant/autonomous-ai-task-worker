import {
  Check,
  GitCompareArrows,
  Loader2,
  Scale,
  ScanText,
  ShieldAlert,
  ShieldCheck,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { StageName } from "@/lib/types";
import type { StageState } from "@/hooks/use-run-stream";
import { JsonView } from "./json-view";

const STAGE_META: Record<StageName, { label: string; blurb: string; icon: LucideIcon }> = {
  extract: { label: "Extract", blurb: "PDF → structured fields", icon: ScanText },
  guardrails: { label: "Guardrails", blurb: "prompt-injection screening", icon: ShieldAlert },
  validate: { label: "Validate", blurb: "arithmetic & required fields", icon: ShieldCheck },
  match: { label: "Match", blurb: "vendor + PO tolerance", icon: GitCompareArrows },
  decide: { label: "Decide", blurb: "deterministic rules engine", icon: Scale },
};

/** One-line summary of a stage's REAL output, shown next to the stage name. */
function summarize(name: StageName, output: Record<string, unknown> | undefined): string {
  if (!output) return "";
  try {
    switch (name) {
      case "extract": {
        const conf = output.extraction_confidence as number | undefined;
        const method = output.method === "vision" ? "vision LLM" : "text-native parse";
        return `${method} · ${conf != null ? Math.round(conf * 100) + "% confidence" : ""}`;
      }
      case "guardrails": {
        const flagged = output.flagged as boolean | undefined;
        const findings = output.findings as unknown[] | undefined;
        return flagged
          ? `flagged - ${findings?.length ?? 0} suspicious pattern(s) detected`
          : "clean - no prompt-injection patterns detected";
      }
      case "validate": {
        const passed = output.passed as boolean | undefined;
        const checks = output.checks as unknown[] | undefined;
        const issues = output.issues as unknown[] | undefined;
        return passed
          ? `${checks?.length ?? "all"} checks passed${issues?.length ? ` · ${issues.length} note(s)` : ""}`
          : "validation failed";
      }
      case "match": {
        const vendor = (output.vendor_match as Record<string, unknown> | null)?.vendor_name;
        const po = (output.po_match as Record<string, unknown> | null)?.po_number;
        if (vendor && po) return `${vendor} · ${po}`;
        if (vendor) return `${vendor} · no PO matched`;
        return "no vendor match";
      }
      case "decide": {
        const reason = output.primary_reason as string | undefined;
        return reason ?? String(output.decision ?? "");
      }
    }
  } catch {
    return "";
  }
  return "";
}

const RING: Record<StageState["status"], string> = {
  idle: "border-border bg-surface text-faint",
  running: "border-primary/60 bg-primary/10 text-primary",
  success: "border-success/50 bg-success/10 text-success",
  error: "border-destructive/50 bg-destructive/10 text-destructive",
};

export function StageNode({
  name,
  state,
}: {
  name: StageName;
  state: StageState;
}) {
  const meta = STAGE_META[name];
  const Icon = meta.icon;
  const { status } = state;
  // The Guardrails stage "succeeds" (it ran fine) even when it flags a
  // finding - flagging is the point, not a failure. Give a flagged run its
  // own warning treatment so it visually stands out from a clean pass.
  const flagged = name === "guardrails" && status === "success" && Boolean(state.output?.flagged);

  return (
    <div
      className={cn(
        "node-in relative min-w-0 rounded-xl border bg-card transition-all duration-300",
        status === "idle" && "border-border opacity-55",
        status === "running" && "border-primary/50 shadow-[0_0_0_3px] shadow-primary/10",
        status === "success" && !flagged && "border-border",
        flagged && "border-warning/50 shadow-[0_0_0_3px] shadow-warning/10",
        status === "error" && "border-destructive/50",
      )}
    >
      <div className="flex items-center gap-3.5 p-4">
        {/* status ring */}
        <div className="relative shrink-0">
          {status === "running" && (
            <span className="ping-soft absolute inset-0 rounded-lg bg-primary/40" />
          )}
          <div
            className={cn(
              "relative flex size-10 items-center justify-center rounded-lg border transition-colors",
              flagged ? "border-warning/50 bg-warning/10 text-warning" : RING[status],
            )}
          >
            {status === "running" ? (
              <Loader2 className="size-4.5 animate-spin" />
            ) : flagged ? (
              <ShieldAlert className="size-4.5" strokeWidth={2.5} />
            ) : status === "success" ? (
              <Check className="size-4.5" strokeWidth={2.5} />
            ) : status === "error" ? (
              <X className="size-4.5" strokeWidth={2.5} />
            ) : (
              <Icon className="size-4.5" />
            )}
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2.5">
            <span className="font-display text-sm font-bold tracking-tight">
              {meta.label}
            </span>
            <span className="truncate text-xs text-muted-foreground">
              {status === "running"
                ? "running…"
                : status === "idle"
                  ? meta.blurb
                  : summarize(name, state.output)}
            </span>
          </div>
        </div>

        {state.durationMs != null && (
          <span className="shrink-0 font-mono text-[10px] text-faint tabular-nums">
            {state.durationMs} ms
          </span>
        )}
      </div>

      {/* Real output, scrollable, revealed on completion (requirement 3) */}
      {state.output && (
        <div className="px-4 pb-4">
          <JsonView data={state.output} />
        </div>
      )}
    </div>
  );
}

/** Connector between two nodes; dashes flow while the downstream stage runs. */
export function StageEdge({ active, done }: { active: boolean; done: boolean }) {
  return (
    <div className="flex h-7 justify-start pl-9" aria-hidden>
      <svg width="2" height="100%" className="overflow-visible">
        <line
          x1="1" y1="0" x2="1" y2="100%"
          className={cn(
            "transition-all",
            active ? "edge-active stroke-primary" : done ? "stroke-success/50" : "stroke-border",
          )}
          strokeWidth="2"
        />
      </svg>
    </div>
  );
}
