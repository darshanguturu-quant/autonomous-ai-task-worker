import { useEffect } from "react";
import { Command } from "cmdk";
import {
  FilePlus2,
  FileText,
  History,
  LayoutDashboard,
  Moon,
  RefreshCw,
  RotateCcw,
  Sun,
} from "lucide-react";
import type { RunSummary } from "@/lib/types";
import { DecisionBadge } from "@/components/ui/badge";

export interface PaletteActions {
  goDashboard: () => void;
  goProcess: () => void;
  openRun: (r: RunSummary) => void;
  refreshRuns: () => void;
  resetDemo: () => void;
  toggleTheme: () => void;
  theme: "dark" | "light";
}

export function CommandPalette({
  open,
  onClose,
  runs,
  actions,
}: {
  open: boolean;
  onClose: () => void;
  runs: RunSummary[] | null;
  actions: PaletteActions;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const run = (fn: () => void) => {
    onClose();
    fn();
  };

  return (
    <div
      className="overlay-in fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="dialog-in mx-auto mt-[16vh] w-full max-w-lg overflow-hidden rounded-xl border border-border bg-card shadow-2xl">
        <Command label="Command menu" loop>
          <Command.Input
            autoFocus
            placeholder="Type a command or search runs…"
            className="h-12 w-full border-b border-border bg-transparent px-4 text-sm placeholder:text-faint focus:outline-none"
          />
          <Command.List className="max-h-80 overflow-y-auto p-2 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-faint [&_[cmdk-group-heading]]:uppercase">
            <Command.Empty className="py-8 text-center text-sm text-muted-foreground">
              No results.
            </Command.Empty>

            <Command.Group heading="Navigate">
              <Item onSelect={() => run(actions.goDashboard)} icon={<LayoutDashboard className="size-4" />}>
                Dashboard
              </Item>
              <Item onSelect={() => run(actions.goProcess)} icon={<FilePlus2 className="size-4" />}>
                Process invoice
              </Item>
            </Command.Group>

            <Command.Group heading="Actions">
              <Item onSelect={() => run(actions.refreshRuns)} icon={<RefreshCw className="size-4" />}>
                Refresh run history
              </Item>
              <Item onSelect={() => run(actions.toggleTheme)} icon={actions.theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}>
                Switch to {actions.theme === "dark" ? "light" : "dark"} mode
              </Item>
              <Item onSelect={() => run(actions.resetDemo)} icon={<RotateCcw className="size-4 text-warning" />}>
                Reset demo state…
              </Item>
            </Command.Group>

            {runs && runs.length > 0 && (
              <Command.Group heading="Recent runs">
                {runs.slice(0, 6).map((r) => (
                  <Item
                    key={r.id}
                    onSelect={() => run(() => actions.openRun(r))}
                    icon={r.status === "failed" ? <FileText className="size-4 text-destructive" /> : <History className="size-4" />}
                  >
                    <span className="font-mono text-xs">#{r.id}</span>
                    <span className="ml-2 truncate">{r.invoice_number ?? r.filename}</span>
                    <span className="ml-auto">
                      <DecisionBadge decision={r.decision} />
                    </span>
                  </Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </div>
    </div>
  );
}

function Item({
  children,
  icon,
  onSelect,
}: {
  children: React.ReactNode;
  icon: React.ReactNode;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-foreground/90 select-none data-[selected=true]:bg-foreground/8"
    >
      <span className="text-muted-foreground">{icon}</span>
      <span className="flex min-w-0 flex-1 items-center">{children}</span>
    </Command.Item>
  );
}
