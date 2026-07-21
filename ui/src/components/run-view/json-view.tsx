import { useMemo } from "react";
import { cn } from "@/lib/utils";

/** Colorized, scrollable pretty-printed JSON. Renders the REAL stage output. */
export function JsonView({
  data,
  className,
  maxHeight = "max-h-56",
}: {
  data: unknown;
  className?: string;
  maxHeight?: string;
}) {
  const html = useMemo(() => highlight(JSON.stringify(data, null, 2)), [data]);
  return (
    <pre
      className={cn(
        "overflow-auto rounded-lg border border-border bg-background/60 p-3",
        "font-mono text-[11px] leading-relaxed whitespace-pre",
        maxHeight,
        className,
      )}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function highlight(json: string): string {
  return escapeHtml(json).replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
    (match, str, colon, literal) => {
      if (str) {
        return colon
          ? `<span class="json-key">${str}</span>${colon}`
          : `<span class="json-str">${str}</span>`;
      }
      if (literal) return `<span class="json-lit">${literal}</span>`;
      return `<span class="json-num">${match}</span>`;
    },
  );
}
