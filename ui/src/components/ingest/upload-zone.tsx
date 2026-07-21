import { useRef, useState } from "react";
import { FileUp, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function UploadZone({
  onUpload,
  busy,
}: {
  onUpload: (file: File) => void;
  busy: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [invalid, setInvalid] = useState(false);

  const accept = (file: File | undefined) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setInvalid(true);
      window.setTimeout(() => setInvalid(false), 2200);
      return;
    }
    onUpload(file);
  };

  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        accept(e.dataTransfer.files[0]);
      }}
      className={cn(
        "dot-grid group flex w-full cursor-pointer flex-col items-center justify-center",
        "rounded-xl border border-dashed px-6 py-12 text-center transition-all",
        dragOver
          ? "border-primary bg-primary/8 scale-[1.005]"
          : invalid
            ? "border-destructive bg-destructive/5"
            : "border-border-strong bg-surface/40 hover:border-primary/50 hover:bg-primary/4",
        busy && "pointer-events-none opacity-60",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,application/pdf"
        className="hidden"
        onChange={(e) => {
          accept(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <div
        className={cn(
          "flex size-12 items-center justify-center rounded-xl border bg-card shadow-sm transition-colors",
          dragOver ? "border-primary text-primary" : "border-border text-muted-foreground group-hover:text-primary",
        )}
      >
        {busy ? <Loader2 className="size-5 animate-spin" /> : <FileUp className="size-5" />}
      </div>
      <p className="font-display mt-4 text-sm font-bold tracking-tight">
        {invalid ? "PDF files only" : dragOver ? "Drop to process" : "Upload an invoice PDF"}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        drag &amp; drop or click to browse — processing starts immediately
      </p>
    </button>
  );
}
