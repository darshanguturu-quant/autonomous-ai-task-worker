import { useEffect, useRef } from "react";
import { ArrowLeft, History, Radio, WifiOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRunStream } from "@/hooks/use-run-stream";
import { STAGE_ORDER } from "@/lib/types";
import { formatMoney } from "@/lib/utils";
import { DecisionBanner, FailureBanner } from "./decision-banner";
import { StageEdge, StageNode } from "./stage-node";

export function PipelineView({
  runId,
  label,
  onBack,
  onFinished,
}: {
  runId: number;
  label: string;
  onBack: () => void;
  onFinished: () => void;
}) {
  const stream = useRunStream(runId);
  const { stages, final, isReplay, connectionLost } = stream;

  // notify once when the run reaches a terminal state (refreshes dashboard)
  const notifiedRef = useRef(false);
  useEffect(() => {
    if (final && !notifiedRef.current) {
      notifiedRef.current = true;
      onFinished();
    }
  }, [final, onFinished]);
  useEffect(() => {
    notifiedRef.current = false;
  }, [runId]);

  const invoice =
    final?.status === "completed"
      ? final.result.invoice
      : extractPreview(stages.extract.output);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5">
      {/* header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={onBack} aria-label="Back to dashboard">
          <ArrowLeft className="size-4" />
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="font-display truncate text-lg font-bold tracking-tight">{label}</h1>
          <p className="text-xs text-muted-foreground">Run #{runId}</p>
        </div>
        {connectionLost && (
          <Badge tone="destructive">
            <WifiOff className="size-3" /> connection lost
          </Badge>
        )}
        {isReplay ? (
          <Badge tone="neutral">
            <History className="size-3" /> REPLAY · stored trace
          </Badge>
        ) : (
          <Badge tone="primary">
            <Radio className="size-3" /> LIVE
          </Badge>
        )}
      </div>

      {final?.status === "completed" && (
        <DecisionBanner
          decision={final.result.decide.decision}
          reason={final.result.decide.primary_reason as string | undefined}
          explanation={final.result.decide.explanation as string | undefined}
        />
      )}
      {final?.status === "failed" && <FailureBanner error={final.error} />}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_260px]">
        {/* node canvas - min-w-0 stops a long unbroken JSON line (e.g. the
            guardrails finding detail) from stretching this whole grid track
            and forcing the entire page to scroll horizontally */}
        <div className="dot-grid min-w-0 rounded-xl border border-border bg-surface/50 p-5">
          {STAGE_ORDER.map((name, i) => (
            <div key={name} className="min-w-0">
              {i > 0 && (
                <StageEdge
                  active={stages[name].status === "running"}
                  done={stages[name].status === "success"}
                />
              )}
              <StageNode name={name} state={stages[name]} />
            </div>
          ))}
        </div>

        {/* side rail: fills in progressively from REAL extract output */}
        <div className="hidden lg:block">
          <Card className="sticky top-20">
            <CardHeader>
              <CardTitle className="text-xs tracking-wider text-muted-foreground uppercase">
                Invoice
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <Fact label="Number" value={invoice?.invoice_number} mono />
              <Fact label="Vendor" value={invoice?.vendor_name} />
              <Fact label="Date" value={invoice?.invoice_date} mono />
              <Fact label="PO ref" value={invoice?.po_ref} mono />
              <Fact label="Total" value={invoice?.total != null ? formatMoney(invoice.total) : null} mono />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Fact({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-xs text-faint">{label}</span>
      {value ? (
        <span className={mono ? "font-mono text-xs tabular-nums" : "truncate text-xs font-medium"}>
          {value}
        </span>
      ) : (
        <span className="h-3 w-16 rounded bg-foreground/6" />
      )}
    </div>
  );
}

/** Pull invoice facts out of the live extract output before the run finishes. */
function extractPreview(output: Record<string, unknown> | undefined) {
  const fields = output?.fields as
    | Record<string, { value: string | number | null }>
    | undefined;
  if (!fields) return null;
  return {
    invoice_number: (fields.invoice_number?.value as string) ?? null,
    vendor_name: (fields.vendor_name?.value as string) ?? null,
    invoice_date: (fields.invoice_date?.value as string) ?? null,
    po_ref: (fields.po_ref?.value as string) ?? null,
    total: (fields.total?.value as number) ?? null,
  };
}
