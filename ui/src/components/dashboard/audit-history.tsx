import { useState } from "react";
import {
  History,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ExternalLink,
  ShieldCheck,
  ChevronRight,
  Database,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog } from "@/components/ui/dialog";
import type { RunSummary } from "@/lib/types";
import { formatMoney } from "@/lib/utils";

interface AuditHistoryProps {
  runs: RunSummary[] | null;
  onOpenRun: (run: RunSummary) => void;
  onClearHistory: () => Promise<void>;
  activeRunId?: number | null;
}

export function AuditHistory({
  runs,
  onOpenRun,
  onClearHistory,
  activeRunId,
}: AuditHistoryProps) {
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [isClearing, setIsClearing] = useState(false);

  const handleConfirmClear = async () => {
    setIsClearing(true);
    try {
      await onClearHistory();
    } finally {
      setIsClearing(false);
      setResetDialogOpen(false);
    }
  };

  const hasRuns = runs && runs.length > 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-display text-sm font-bold tracking-tight text-foreground">
              Processing Run Audit Log
            </h3>
            {hasRuns && (
              <span className="rounded-full bg-surface border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                {runs.length} runs persisted
              </span>
            )}
          </div>
        </div>

        {hasRuns && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setResetDialogOpen(true)}
            className="gap-1.5 text-xs text-warning border-warning/30 hover:bg-warning/10"
          >
            <RotateCcw className="size-3.5" />
            Clear Run History
          </Button>
        )}
      </div>

      {!hasRuns ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/60 p-8 text-center">
          <Database className="size-8 text-faint" />
          <p className="mt-2 text-xs font-semibold text-foreground">
            No runs yet
          </p>
          <p className="max-w-md mt-1 text-[11px] text-muted-foreground">
            Uploaded invoices and their processing results will appear here.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border bg-surface text-faint uppercase tracking-wider">
                <tr>
                  <th className="py-2.5 pr-3 pl-4 font-semibold">Run ID</th>
                  <th className="py-2.5 pr-3 pl-2 font-semibold">Timestamp</th>
                  <th className="py-2.5 pr-3 pl-2 font-semibold">Source Document</th>
                  <th className="py-2.5 pr-3 pl-2 font-semibold">Vendor</th>
                  <th className="py-2.5 pr-3 pl-2 font-semibold">Total Amount</th>
                  <th className="py-2.5 pr-3 pl-2 font-semibold">Status / Decision</th>
                  <th className="py-2.5 pr-4 pl-2 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {runs.map((r) => {
                  const isActive = activeRunId === r.id;
                  return (
                    <tr
                      key={r.id}
                      onClick={() => onOpenRun(r)}
                      className={`cursor-pointer transition-colors ${
                        isActive
                          ? "bg-primary/10 hover:bg-primary/15"
                          : "hover:bg-surface/60"
                      }`}
                    >
                      <td className="py-2.5 pr-3 pl-4 font-mono text-[11px] font-bold text-foreground">
                        #{r.id}
                      </td>
                      <td className="py-2.5 pr-3 pl-2 whitespace-nowrap font-mono text-[11px] text-muted-foreground">
                        {r.created_at?.replace("T", " ")?.slice(0, 19) || "Recent"}
                      </td>
                      <td className="py-2.5 pr-3 pl-2 font-mono text-xs font-medium text-foreground">
                        <span className="truncate max-w-[200px] inline-block">
                          {r.filename}
                        </span>
                      </td>
                      <td className="py-2.5 pr-3 pl-2 text-foreground/90 font-medium">
                        {r.vendor_name || <span className="text-faint">—</span>}
                      </td>
                      <td className="py-2.5 pr-3 pl-2 font-mono text-xs font-semibold text-foreground">
                        {r.total != null ? (
                          formatMoney(r.total)
                        ) : (
                          <span className="text-faint">—</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 pl-2 whitespace-nowrap">
                        {r.status === "failed" ? (
                          <span className="inline-flex items-center gap-1 rounded-sm bg-destructive/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-destructive">
                            <XCircle className="size-3" /> FAILED
                          </span>
                        ) : r.decision === "auto_approve" ? (
                          <span className="inline-flex items-center gap-1 rounded-sm bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-emerald-600 dark:text-emerald-400">
                            <CheckCircle2 className="size-3" /> AUTO-APPROVE
                          </span>
                        ) : r.decision === "needs_review" ? (
                          <span className="inline-flex items-center gap-1 rounded-sm bg-amber-500/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-amber-600 dark:text-amber-400">
                            <AlertTriangle className="size-3" /> NEEDS REVIEW
                          </span>
                        ) : r.decision === "reject" ? (
                          <span className="inline-flex items-center gap-1 rounded-sm bg-rose-500/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-rose-600 dark:text-rose-400">
                            <XCircle className="size-3" /> REJECT
                          </span>
                        ) : (
                          <span className="text-muted-foreground text-[11px]">
                            {r.status}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-4 pl-2 text-right">
                        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-primary hover:underline">
                          Inspect <ChevronRight className="size-3" />
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Confirmation Dialog */}
      <Dialog open={resetDialogOpen} onClose={() => setResetDialogOpen(false)}>
        <div className="flex items-start gap-3.5">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-warning/40 bg-warning/10 text-warning">
            <RotateCcw className="size-4.5" />
          </div>
          <div>
            <h2 className="font-display text-base font-bold tracking-tight text-foreground">
              Clear run history?
            </h2>
            <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
              This deletes all recorded run history from SQLite. Duplicate detection and cumulative purchase-order billing will start fresh. Master vendor and purchase-order datasets remain untouched.
            </p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setResetDialogOpen(false)}
            disabled={isClearing}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={handleConfirmClear}
            disabled={isClearing}
          >
            {isClearing ? "Clearing…" : "Confirm Delete"}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
