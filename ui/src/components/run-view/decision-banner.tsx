import { CheckCircle2, CircleAlert, TriangleAlert, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Decision } from "@/lib/types";

const META: Record<
  Decision,
  { icon: typeof CheckCircle2; frame: string; iconCls: string; label: string }
> = {
  auto_approve: {
    icon: CheckCircle2,
    frame: "border-success/40 bg-success/8",
    iconCls: "text-success",
    label: "Auto-Approve",
  },
  needs_review: {
    icon: TriangleAlert,
    frame: "border-warning/40 bg-warning/8",
    iconCls: "text-warning",
    label: "Needs Review",
  },
  reject: {
    icon: XCircle,
    frame: "border-destructive/40 bg-destructive/8",
    iconCls: "text-destructive",
    label: "Reject",
  },
};

export function DecisionBanner({
  decision,
  reason,
  explanation,
}: {
  decision: Decision;
  reason?: string;
  explanation?: string;
}) {
  const meta = META[decision];
  const Icon = meta.icon;
  return (
    <div className={cn("node-in flex gap-4 rounded-xl border p-5", meta.frame)}>
      <Icon className={cn("mt-0.5 size-6 shrink-0", meta.iconCls)} />
      <div className="min-w-0">
        <div className="font-display text-base font-bold tracking-tight">{meta.label}</div>
        {reason && <p className="mt-1 text-sm text-muted-foreground">{reason}</p>}
        {explanation && explanation !== reason && (
          <p className="mt-2 text-sm leading-relaxed text-foreground/85">{explanation}</p>
        )}
      </div>
    </div>
  );
}

export function FailureBanner({ error }: { error: string }) {
  return (
    <div className="node-in flex gap-4 rounded-xl border border-destructive/40 bg-destructive/8 p-5">
      <CircleAlert className="mt-0.5 size-6 shrink-0 text-destructive" />
      <div>
        <div className="font-display text-base font-bold tracking-tight">Run failed</div>
        <p className="mt-1 text-sm text-muted-foreground">{error}</p>
      </div>
    </div>
  );
}
