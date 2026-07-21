import { useState } from "react";
import { FilePlus2, LayoutDashboard, Menu, RotateCcw, ScanLine } from "lucide-react";
import { cn } from "@/lib/utils";
import { Kbd } from "@/components/ui/kbd";

export type View = "dashboard" | "process" | "run";

const NAV = [
  { view: "dashboard" as const, label: "Dashboard", icon: LayoutDashboard },
  { view: "process" as const, label: "Process invoice", icon: FilePlus2 },
];

export function Sidebar({
  view,
  onNavigate,
  onResetDemo,
  onOpenPalette,
}: {
  view: View;
  onNavigate: (v: View) => void;
  onResetDemo: () => void;
  onOpenPalette: () => void;
}) {
  // Hidden by default - only the hamburger toggle reveals Dashboard / Process invoice.
  const [navOpen, setNavOpen] = useState(false);

  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-border bg-surface/70 backdrop-blur md:flex">
      {/* brand + hamburger toggle */}
      <div className="flex h-14 items-center gap-2.5 border-b border-border px-4">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <ScanLine className="size-4" />
        </div>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="font-display text-[13px] font-extrabold tracking-tight">
            Invoice Processing
          </div>
          <div className="text-[10px] text-faint">Extract · Guardrails · Validate · Match · Decide</div>
        </div>
        <button
          onClick={() => setNavOpen((o) => !o)}
          aria-expanded={navOpen}
          aria-label={navOpen ? "Collapse navigation menu" : "Expand navigation menu"}
          className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
        >
          <Menu className="size-4.5" />
        </button>
      </div>

      {/* nav - collapsed to zero height by default, slides open/closed */}
      <div
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-out",
          navOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <nav className="overflow-hidden">
          <div className="space-y-1 p-3">
            {NAV.map(({ view: v, label, icon: Icon }) => {
              const active = view === v || (v === "dashboard" && view === "run");
              return (
                <button
                  key={v}
                  onClick={() => onNavigate(v)}
                  className={cn(
                    "flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                    active
                      ? "bg-foreground/8 font-semibold text-foreground"
                      : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
                  )}
                >
                  <Icon className="size-4" />
                  {label}
                </button>
              );
            })}
          </div>
        </nav>
      </div>

      <div className="flex-1" />

      {/* footer actions */}
      <div className="space-y-1 border-t border-border p-3">
        <button
          onClick={onOpenPalette}
          className="flex w-full cursor-pointer items-center justify-between rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground"
        >
          <span>Command menu</span>
          <span className="flex gap-1">
            <Kbd>Ctrl</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>
        <button
          onClick={onResetDemo}
          title="Clears run history AND all processing state: duplicate detection and cumulative PO billing start fresh"
          className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-warning transition-colors hover:bg-warning/10"
        >
          <RotateCcw className="size-4" />
          Reset demo state
        </button>
      </div>
    </aside>
  );
}
