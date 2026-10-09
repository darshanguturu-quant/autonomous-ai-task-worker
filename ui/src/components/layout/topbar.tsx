import { Moon, Sun, ShieldCheck, Binary } from "lucide-react";
import { Button } from "@/components/ui/button";

interface TopbarProps {
  theme: "dark" | "light";
  onToggleTheme: () => void;
}

export function Topbar({ theme, onToggleTheme }: TopbarProps) {
  return (
    <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-border bg-background/85 px-4 backdrop-blur-md sm:px-8">
      {/* Brand Identity */}
      <div className="flex items-center gap-3">
        <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-xs">
          <Binary className="size-5" />
        </div>
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <span className="font-display text-base font-extrabold tracking-tight text-foreground">
              CentrAlign AI
            </span>
            <span className="rounded-md border border-primary/30 bg-primary/10 px-1.5 py-0.2 font-mono text-[9px] font-bold tracking-wider text-primary uppercase">
              Enterprise
            </span>
          </div>
        </div>
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-3">
        <div className="hidden items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1 text-xs text-muted-foreground md:flex">
          <ShieldCheck className="size-3.5 text-success" />
          <span className="font-mono text-[11px]">Audit Engine Active</span>
        </div>

        <Button
          variant="outline"
          size="icon"
          onClick={onToggleTheme}
          aria-label="Toggle visual theme"
          className="size-8 rounded-lg"
        >
          {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
      </div>
    </header>
  );
}
