import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, RotateCcw } from "lucide-react";
import { CommandPalette } from "@/components/layout/command-palette";
import { Sidebar, type View } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { KpiCards } from "@/components/dashboard/kpi-cards";
import { RunsTable } from "@/components/dashboard/runs-table";
import { UploadZone } from "@/components/ingest/upload-zone";
import { PipelineView } from "@/components/run-view/pipeline-view";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useTheme } from "@/hooks/use-theme";
import { api } from "@/lib/api";
import type { RunSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ActiveRun {
  id: number;
  label: string;
}

interface Toast {
  id: number;
  kind: "success" | "error";
  message: string;
}

export default function App() {
  const { theme, toggle: toggleTheme } = useTheme();
  const [view, setView] = useState<View>("dashboard");
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((kind: Toast["kind"], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, message }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3800);
  }, []);

  const refreshRuns = useCallback(() => {
    api.listRuns().then(setRuns).catch(() => toast("error", "Could not load run history"));
  }, [toast]);

  useEffect(() => {
    refreshRuns();
  }, [refreshRuns]);

  // Ctrl/Cmd+K opens the palette
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const startRun = useCallback(
    async (fn: () => Promise<{ run_id: number }>, label: string) => {
      setBusy(true);
      try {
        const { run_id } = await fn();
        setActiveRun({ id: run_id, label });
        setView("run");
      } catch (e) {
        toast("error", e instanceof Error ? e.message : "Could not start the run");
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );

  const uploadFile = useCallback(
    (file: File) => void startRun(() => api.uploadInvoice(file), file.name),
    [startRun],
  );

  const openRun = useCallback((r: RunSummary) => {
    setActiveRun({ id: r.id, label: r.invoice_number ?? r.filename });
    setView("run");
  }, []);

  const doReset = useCallback(async () => {
    setResetOpen(false);
    try {
      const { deleted } = await api.resetDemoState();
      setActiveRun(null);
      setView("dashboard");
      refreshRuns();
      toast("success", `Demo state reset — ${deleted} run(s) cleared, dedup & PO history fresh`);
    } catch {
      toast("error", "Reset failed — is the backend running?");
    }
  }, [refreshRuns, toast]);

  const titles: Record<View, string> = {
    dashboard: "Dashboard",
    process: "Process invoice",
    run: activeRun ? `Run · ${activeRun.label}` : "Run",
  };

  return (
    <div className="min-h-full">
      <Sidebar
        view={view}
        onNavigate={setView}
        onResetDemo={() => setResetOpen(true)}
        onOpenPalette={() => setPaletteOpen(true)}
      />

      <div className="md:pl-60">
        <Topbar
          title={titles[view]}
          theme={theme}
          onToggleTheme={toggleTheme}
          onOpenPalette={() => setPaletteOpen(true)}
        />

        <main className="mx-auto max-w-6xl space-y-6 p-5 md:p-8">
          {view === "dashboard" && (
            <>
              <KpiCards runs={runs} />
              <RunsTable
                runs={runs}
                onOpenRun={openRun}
                onGoProcess={() => setView("process")}
              />
            </>
          )}

          {view === "process" && (
            <div className="mx-auto max-w-4xl space-y-8">
              <UploadZone onUpload={uploadFile} busy={busy} />
            </div>
          )}

          {view === "run" && activeRun && (
            <PipelineView
              runId={activeRun.id}
              label={activeRun.label}
              onBack={() => setView("dashboard")}
              onFinished={refreshRuns}
            />
          )}
        </main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        runs={runs}
        actions={{
          goDashboard: () => setView("dashboard"),
          goProcess: () => setView("process"),
          openRun,
          refreshRuns,
          resetDemo: () => setResetOpen(true),
          toggleTheme,
          theme,
        }}
      />

      {/* Reset demo state confirmation */}
      <Dialog open={resetOpen} onClose={() => setResetOpen(false)}>
        <div className="flex items-start gap-3.5">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-warning/40 bg-warning/10 text-warning">
            <RotateCcw className="size-4.5" />
          </div>
          <div>
            <h2 className="font-display text-base font-bold tracking-tight">
              Reset demo state?
            </h2>
            <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
              Deletes all run history so <strong className="text-foreground">duplicate
              detection</strong> and <strong className="text-foreground">cumulative PO
              billing</strong> start completely fresh — not just a display clear.
            </p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setResetOpen(false)}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={doReset}>
            Reset everything
          </Button>
        </div>
      </Dialog>

      {/* toasts */}
      <div className="fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "toast-in flex items-start gap-2.5 rounded-lg border bg-card p-3.5 text-sm shadow-lg",
              t.kind === "success" ? "border-success/40" : "border-destructive/40",
            )}
          >
            {t.kind === "success" ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
            ) : (
              <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
            )}
            <span className="leading-snug">{t.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
