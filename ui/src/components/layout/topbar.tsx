import { Moon, Search, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";

export function Topbar({
  title,
  theme,
  onToggleTheme,
  onOpenPalette,
}: {
  title: string;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onOpenPalette: () => void;
}) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-background/80 px-5 backdrop-blur md:px-8">
      <h1 className="font-display flex-1 truncate text-sm font-bold tracking-tight">
        {title}
      </h1>
      <button
        onClick={onOpenPalette}
        className="hidden h-8 cursor-pointer items-center gap-2 rounded-md border border-border bg-surface px-2.5 text-xs text-faint transition-colors hover:border-border-strong hover:text-muted-foreground sm:flex"
      >
        <Search className="size-3.5" />
        <span>Search or jump…</span>
        <Kbd className="ml-2">Ctrl K</Kbd>
      </button>
      <Button
        variant="ghost"
        size="icon"
        onClick={onToggleTheme}
        aria-label="Toggle theme"
      >
        {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
      </Button>
    </header>
  );
}
