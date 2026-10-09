import { useState } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ShieldAlert,
  ChevronDown,
  Layers,
  Sparkles,
  Search,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Decision, RunTrace } from "@/lib/types";
import { cn, formatMoney } from "@/lib/utils";
import { JsonView } from "./json-view";

interface RuleRow {
  rule: string;
  name: string;
  category: string;
  triggered: boolean;
  effect: Decision | "pass";
  detail: string;
}

const RULE_METADATA: Record<string, { name: string; category: string; defaultEffect: Decision }> = {
  R0_prompt_injection_detected: {
    name: "Prompt Injection Screening",
    category: "Guardrail",
    defaultEffect: "needs_review",
  },
  R1_duplicate_invoice: {
    name: "Duplicate Invoice Detection",
    category: "Deduplication",
    defaultEffect: "reject",
  },
  R2_validation_failed: {
    name: "Integrity & Arithmetic Validation",
    category: "Integrity",
    defaultEffect: "needs_review",
  },
  R3_vendor_unknown_or_unapproved: {
    name: "Approved Vendor Master Check",
    category: "Master Data",
    defaultEffect: "reject",
  },
  R4_no_po_found: {
    name: "Purchase Order Association",
    category: "Procurement",
    defaultEffect: "needs_review",
  },
  R5_low_extraction_confidence: {
    name: "Extraction Legibility Threshold",
    category: "Confidence",
    defaultEffect: "needs_review",
  },
  R6_fuzzy_po_needs_confirmation: {
    name: "Unreferenced PO Confirmation",
    category: "Compliance",
    defaultEffect: "needs_review",
  },
  R7_amount_out_of_tolerance: {
    name: "PO Amount Tolerance Boundary",
    category: "Financial",
    defaultEffect: "needs_review",
  },
  R7_cumulative_exceeds_po: {
    name: "Cumulative PO Split Billing Limit",
    category: "Financial",
    defaultEffect: "needs_review",
  },
  R7_amount_check: {
    name: "Amount Check Feasibility",
    category: "Financial",
    defaultEffect: "needs_review",
  },
  R8_amount_exceeds_auto_approval_cap: {
    name: "Auto-Approval Hard Cap ($25,000)",
    category: "Governance",
    defaultEffect: "needs_review",
  },
};

export function DecisionEvidenceSection({ trace }: { trace: RunTrace }) {
  const { decide, extract, guardrails, validate, match } = trace;
  const decision = decide.decision as Decision;
  const reason = decide.primary_reason as string | undefined;
  const explanation = decide.explanation as string | undefined;
  const rawRulesTrace = (decide.rules_trace as Array<{
    rule: string;
    triggered: boolean;
    detail: string;
  }>) || [];

  const [activeStageTab, setActiveStageTab] = useState<string | null>(null);

  const rules: RuleRow[] = rawRulesTrace.map((r) => {
    const meta = RULE_METADATA[r.rule] || {
      name: r.rule,
      category: "Policy",
      defaultEffect: "needs_review" as Decision,
    };
    return {
      rule: r.rule,
      name: meta.name,
      category: meta.category,
      triggered: r.triggered,
      effect: r.triggered ? meta.defaultEffect : "pass",
      detail: r.detail,
    };
  });

  const bannerMeta = {
    auto_approve: {
      label: "AUTO-APPROVE",
      icon: CheckCircle2,
      frame: "border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
      badgeClass: "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-black",
      iconCls: "text-emerald-600 dark:text-emerald-400",
      tagline: "Invoice verified against master data, within tolerance, and approved without human intervention.",
    },
    needs_review: {
      label: "NEEDS HUMAN REVIEW",
      icon: AlertTriangle,
      frame: "border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-300",
      badgeClass: "bg-amber-600 text-white dark:bg-amber-500 dark:text-black",
      iconCls: "text-amber-600 dark:text-amber-400",
      tagline: "Deterministic policies require manual verification before payment release.",
    },
    reject: {
      label: "REJECT",
      icon: XCircle,
      frame: "border-rose-500/30 bg-rose-500/10 text-rose-800 dark:text-rose-300",
      badgeClass: "bg-rose-600 text-white dark:bg-rose-500 dark:text-black",
      iconCls: "text-rose-600 dark:text-rose-400",
      tagline: "Document violates critical verification policies (unapproved vendor or duplicate transaction).",
    },
  }[decision];

  const BannerIcon = bannerMeta.icon;

  const stageDataMap: Record<string, { name: string; data: unknown }> = {
    extract: { name: "1. Extract", data: extract },
    guardrails: { name: "2. Guardrails", data: guardrails },
    validate: { name: "3. Validate", data: validate },
    match: { name: "4. Match", data: match },
    decide: { name: "5. Decide", data: decide },
  };

  return (
    <div className="space-y-6">
      {/* 1. Prominent Decision Outcome Banner */}
      <div
        className={cn(
          "rounded-xl border p-5 shadow-xs transition-all",
          bannerMeta.frame
        )}
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-background/80 shadow-xs">
            <BannerIcon className={cn("size-7", bannerMeta.iconCls)} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "rounded-md px-2.5 py-0.5 font-mono text-xs font-bold tracking-wider uppercase",
                  bannerMeta.badgeClass
                )}
              >
                {bannerMeta.label}
              </span>
              <span className="text-xs font-medium text-foreground/80">
                {bannerMeta.tagline}
              </span>
            </div>
            {reason && (
              <p className="mt-2 text-sm font-semibold tracking-tight text-foreground">
                Primary Trigger: {reason}
              </p>
            )}
            {explanation && explanation !== reason && (
              <p className="mt-1.5 text-xs leading-relaxed text-foreground/80">
                {explanation}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* 2. Deterministic Rules Evaluation Matrix */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-display text-sm font-bold tracking-tight text-foreground">
              Deterministic Rules Engine Evaluation Matrix
            </h3>
            <p className="text-xs text-muted-foreground">
              Rules are evaluated strictly in sequence. The first triggered terminal rule determines the outcome. AI never makes the approval decision.
            </p>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border bg-surface text-faint uppercase tracking-wider">
                <tr>
                  <th className="py-2.5 pr-4 pl-4 font-semibold">Rule ID</th>
                  <th className="py-2.5 pr-4 pl-2 font-semibold">Policy Check</th>
                  <th className="py-2.5 pr-4 pl-2 font-semibold">Category</th>
                  <th className="py-2.5 pr-4 pl-2 font-semibold">Evaluation Status</th>
                  <th className="py-2.5 pr-4 pl-2 font-semibold">Audit Trace &amp; Evidence Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {rules.map((r) => (
                  <tr
                    key={r.rule}
                    className={cn(
                      "transition-colors",
                      r.triggered
                        ? r.effect === "reject"
                          ? "bg-rose-500/5 dark:bg-rose-950/20"
                          : "bg-amber-500/5 dark:bg-amber-950/20"
                        : "hover:bg-surface/50"
                    )}
                  >
                    <td className="py-2.5 pr-4 pl-4 font-mono text-[11px] font-bold text-foreground">
                      {r.rule.split("_")[0]}
                    </td>
                    <td className="py-2.5 pr-4 pl-2 font-medium text-foreground">
                      {r.name}
                    </td>
                    <td className="py-2.5 pr-4 pl-2 text-muted-foreground">
                      <span className="rounded-sm bg-surface px-1.5 py-0.5 text-[10px] font-medium">
                        {r.category}
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 pl-2 whitespace-nowrap">
                      {r.triggered ? (
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-bold",
                            r.effect === "reject"
                              ? "bg-rose-500/20 text-rose-600 dark:text-rose-400"
                              : "bg-amber-500/20 text-amber-600 dark:text-amber-400"
                          )}
                        >
                          <AlertTriangle className="size-3" /> TRIGGERED ({r.effect.toUpperCase().replace("_", " ")})
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-sm bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-emerald-600 dark:text-emerald-400">
                          <CheckCircle2 className="size-3" /> PASSED
                        </span>
                      )}
                    </td>
                    <td className="max-w-md py-2.5 pr-4 pl-2 font-mono text-[11px] leading-relaxed text-foreground/80">
                      {r.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* 3. Per-Stage Audit Trail & Deep Inspector */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-display text-sm font-bold tracking-tight text-foreground">
              Per-Stage Audit Trail &amp; Evidence Inspector
            </h3>
            <p className="text-xs text-muted-foreground">
              Direct access to raw immutable outputs from each of the five pipeline stages.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {Object.entries(stageDataMap).map(([key, item]) => {
            const isActive = activeStageTab === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setActiveStageTab(isActive ? null : key)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all",
                  isActive
                    ? "border-primary bg-primary text-primary-foreground shadow-xs"
                    : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground"
                )}
              >
                <span>{item.name}</span>
                <ChevronDown
                  className={cn("size-3.5 transition-transform", isActive && "rotate-180")}
                />
              </button>
            );
          })}
        </div>

        {activeStageTab && (
          <div className="rounded-xl border border-border bg-card p-4 shadow-xs">
            <div className="mb-2 flex items-center justify-between border-b border-border pb-2">
              <span className="font-mono text-xs font-bold text-foreground">
                Payload Inspector: {stageDataMap[activeStageTab]?.name}
              </span>
              <button
                type="button"
                onClick={() => setActiveStageTab(null)}
                className="cursor-pointer text-xs text-muted-foreground hover:text-foreground"
              >
                Close
              </button>
            </div>
            <JsonView value={stageDataMap[activeStageTab]?.data} />
          </div>
        )}
      </div>
    </div>
  );
}
