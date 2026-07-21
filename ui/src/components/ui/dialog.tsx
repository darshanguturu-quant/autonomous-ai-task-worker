import { useEffect, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Minimal modal (shadcn Dialog pattern without the Radix dependency). */
export function Dialog({
  open,
  onClose,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="overlay-in fixed inset-0 z-50 flex items-start justify-center bg-black/55 pt-[18vh] backdrop-blur-[2px]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          "dialog-in w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-2xl",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}
