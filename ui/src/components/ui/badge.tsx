import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import type { Decision } from "@/lib/types";

type Tone = "success" | "warning" | "destructive" | "neutral" | "primary";

const tones: Record<Tone, string> = {
  success: "bg-success/12 text-success border-success/30",
  warning: "bg-warning/12 text-warning border-warning/30",
  destructive: "bg-destructive/12 text-destructive border-destructive/30",
  neutral: "bg-foreground/6 text-muted-foreground border-border",
  primary: "bg-primary/12 text-primary border-primary/30",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5",
        "text-[11px] font-semibold tracking-wide whitespace-nowrap",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}

/** Single source of truth for decision colors (requirement 4). */
export const DECISION_META: Record<
  Decision,
  { label: string; tone: Tone; dot: string }
> = {
  auto_approve: { label: "Auto-Approve", tone: "success", dot: "bg-success" },
  needs_review: { label: "Needs Review", tone: "warning", dot: "bg-warning" },
  reject: { label: "Reject", tone: "destructive", dot: "bg-destructive" },
};

export function DecisionBadge({ decision }: { decision: Decision | null }) {
  if (!decision) return <span className="text-faint text-xs">—</span>;
  const meta = DECISION_META[decision];
  return (
    <Badge tone={meta.tone}>
      <span className={cn("size-1.5 rounded-full", meta.dot)} />
      {meta.label}
    </Badge>
  );
}
