import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { Topbar } from "@/components/layout/topbar";
import { UploadBox } from "@/components/ingest/upload-box";
import { ProcessingStatusArea } from "@/components/run-view/processing-status-area";
import { StructuredResultsTable } from "@/components/run-view/structured-results-table";
import { DecisionEvidenceSection } from "@/components/run-view/decision-evidence-section";
import { AuditHistory } from "@/components/dashboard/audit-history";
import { WorkerPanel } from "@/components/worker/worker-panel";
import { useTheme } from "@/hooks/use-theme";
import { useRunStream } from "@/hooks/use-run-stream";
import { api } from "@/lib/api";
import type { RunSummary, RunTrace } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Toast {
  id: number;
  kind: "success" | "error";
  message: string;
}

export default function App() {
  const { theme, toggle: toggleTheme } = useTheme();

  // Run and data states
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [activeFilename, setActiveFilename] = useState<string | undefined>(undefined);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  // SSE Stream hook for live or replayed run
  const stream = useRunStream(activeRunId);
  const { stages, final } = stream;

  const toast = useCallback((kind: Toast["kind"], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, message }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);

  const refreshRuns = useCallback(() => {
    api
      .listRuns()
      .then(setRuns)
      .catch(() => {
        // Silently handle if backend is starting
      });
  }, []);

  useEffect(() => {
    refreshRuns();
  }, [refreshRuns]);

  // When run finishes successfully or fails, refresh audit log
  useEffect(() => {
    if (final) {
      refreshRuns();
      if (final.status === "completed") {
        toast("success", "Document processing and verification completed.");
      } else if (final.status === "failed") {
        toast("error", `Processing failed: ${final.error}`);
      }
    }
  }, [final, refreshRuns, toast]);

  // Handle genuine file upload
  const handleUpload = useCallback(
    async (file: File) => {
      setUploadError(null);
      setIsUploading(true);
      setActiveFilename(file.name);

      try {
        const { run_id } = await api.uploadInvoice(file);
        setActiveRunId(run_id);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to upload invoice document.";
        setUploadError(msg);
        toast("error", msg);
      } finally {
        setIsUploading(false);
      }
    },
    [toast]
  );

  // Handle reopening a past genuine run from the audit log
  const handleOpenRun = useCallback((r: RunSummary) => {
    setUploadError(null);
    setActiveFilename(r.filename);
    setActiveRunId(r.id);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  // Reset demo / run history
  const handleClearHistory = useCallback(async () => {
    try {
      const { deleted } = await api.resetDemoState();
      setActiveRunId(null);
      setActiveFilename(undefined);
      setUploadError(null);
      refreshRuns();
      toast("success", `Run history reset — cleared ${deleted} persisted record(s).`);
    } catch {
      toast("error", "Failed to clear run history.");
    }
  }, [refreshRuns, toast]);

  // Reset active document view to upload fresh
  const handleResetActiveDoc = useCallback(() => {
    setActiveRunId(null);
    setActiveFilename(undefined);
    setUploadError(null);
  }, []);

  const isPipelineRunning =
    isUploading ||
    (activeRunId != null &&
      final == null &&
      Object.values(stages).some((s) => s.status === "running" || s.status === "idle"));

  const completedTrace: RunTrace | null =
    final?.status === "completed" ? final.result : null;

  const failedError =
    uploadError || (final?.status === "failed" ? final.error : null);

  return (
    <div className="min-h-full flex flex-col bg-background text-foreground antialiased selection:bg-primary/20">
      {/* 1. CentrAlign AI Header */}
      <Topbar theme={theme} onToggleTheme={toggleTheme} />

      <main className="mx-auto w-full max-w-5xl flex-1 space-y-8 p-4 sm:p-6 md:p-8">
        <section aria-label="Autonomous task worker">
          <WorkerPanel onTaskCompleted={refreshRuns} />
        </section>

        {/* 3. Central Document-Upload Box */}
        <section aria-label="Document Upload Area">
          <UploadBox
            onUpload={handleUpload}
            isProcessing={isPipelineRunning}
            activeFilename={activeFilename}
            onReset={handleResetActiveDoc}
            statusMessage={
              isUploading
                ? "Verifying file integrity and uploading…"
                : "Executing deterministic five-stage pipeline…"
            }
          />
        </section>

        {/* 4. Document-Processing Status Area (Displayed after upload / when active) */}
        {(activeRunId != null || failedError) && (
          <section aria-label="Processing Status Flow">
            <ProcessingStatusArea
              stages={stages}
              isProcessing={isPipelineRunning}
              isComplete={completedTrace != null}
              failedError={failedError}
              totalDurationMs={
                final?.status === "completed" ? undefined : undefined
              }
            />
          </section>
        )}

        {/* 5. Structured Results Table (Displayed only when actual results are available) */}
        {completedTrace && (
          <section aria-label="Structured Extraction & Verification Results">
            <StructuredResultsTable trace={completedTrace} />
          </section>
        )}

        {/* 6. Decision and Evidence Section */}
        {completedTrace && (
          <section aria-label="Decision and Deterministic Evidence">
            <DecisionEvidenceSection trace={completedTrace} />
          </section>
        )}

        {/* 7. Processing Run Audit History (Genuine Runs Only) */}
        <section aria-label="Audit History" className="border-t border-border pt-6">
          <AuditHistory
            runs={runs}
            onOpenRun={handleOpenRun}
            onClearHistory={handleClearHistory}
            activeRunId={activeRunId}
          />
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-surface/50 py-4 text-center text-xs text-muted-foreground">
        CentrAlign AI — Invoice Processing &amp; Verification
      </footer>

      {/* Toast Notification Stack */}
      <div className="fixed right-4 bottom-4 z-50 flex w-84 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "flex items-start gap-2.5 rounded-xl border bg-card p-3.5 text-xs shadow-lg transition-all",
              t.kind === "success"
                ? "border-emerald-500/40 text-foreground"
                : "border-destructive/40 text-foreground"
            )}
          >
            {t.kind === "success" ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
            )}
            <span className="leading-relaxed font-medium">{t.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
