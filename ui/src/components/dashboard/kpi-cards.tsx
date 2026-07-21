import { Activity, BadgeCheck, TriangleAlert, XOctagon } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { RunSummary } from "@/lib/types";

export function KpiCards({ runs }: { runs: RunSummary[] | null }) {
  if (runs === null) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-3.5 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-16" />
              <Skeleton className="mt-2 h-3 w-32" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const today = new Date().toISOString().slice(0, 10);
  const todayCount = runs.filter((r) => r.created_at.startsWith(today)).length;
  const decided = runs.filter((r) => r.status === "completed" && r.decision);
  const approved = decided.filter((r) => r.decision === "auto_approve").length;
  const review = decided.filter((r) => r.decision === "needs_review").length;
  const rejected = decided.filter((r) => r.decision === "reject").length;
  const failed = runs.filter((r) => r.status === "failed").length;
  const rate = decided.length ? Math.round((approved / decided.length) * 100) : null;

  const cards = [
    {
      title: "Runs today",
      icon: Activity,
      value: String(todayCount),
      sub: `${runs.length} all time`,
      accent: "text-primary",
    },
    {
      title: "Approval rate",
      icon: BadgeCheck,
      value: rate != null ? `${rate}%` : "—",
      sub: `${approved} auto-approved of ${decided.length} decided`,
      accent: "text-success",
    },
    {
      title: "Needs review",
      icon: TriangleAlert,
      value: String(review),
      sub: "tolerance breaches · fuzzy matches",
      accent: "text-warning",
    },
    {
      title: "Rejected",
      icon: XOctagon,
      value: String(rejected),
      sub: failed ? `duplicates & unknown vendors · ${failed} failed` : "duplicates & unknown vendors",
      accent: "text-destructive",
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map(({ title, icon: Icon, value, sub, accent }) => (
        <Card key={title}>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <span className="text-xs font-medium tracking-wide text-muted-foreground">
              {title}
            </span>
            <Icon className={cn("size-4", accent)} />
          </CardHeader>
          <CardContent>
            <div className="font-display text-2xl font-extrabold tracking-tight tabular-nums">
              {value}
            </div>
            <p className="mt-1 text-xs text-faint">{sub}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
