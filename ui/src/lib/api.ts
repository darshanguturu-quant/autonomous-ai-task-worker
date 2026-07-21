import type { RunDetail, RunSummary, StreamEvent } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch { /* keep status text */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listRuns: () => fetch("/api/runs").then((r) => json<RunSummary[]>(r)),
  getRun: (id: number) => fetch(`/api/runs/${id}`).then((r) => json<RunDetail>(r)),

  /** Upload a PDF as a deferred run; execution happens on the SSE stream. */
  uploadInvoice: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/invoices?defer=1", { method: "POST", body: form })
      .then((r) => json<{ run_id: number; status: string }>(r));
  },

  /** Full demo reset: deletes run history, so dedup + cumulative PO state start fresh. */
  resetDemoState: () =>
    fetch("/api/runs", { method: "DELETE" }).then((r) => json<{ deleted: number }>(r)),
};

/**
 * Open the SSE stream for a run. Every event is a REAL pipeline stage
 * execution (or a replay of the stored trace, flagged with replay=true).
 * The server closes the stream after the final `pipeline` event; we close
 * the EventSource on that event so the browser doesn't auto-reconnect.
 */
export function openRunStream(
  runId: number,
  onEvent: (ev: StreamEvent) => void,
  onConnectionError: () => void,
): () => void {
  const es = new EventSource(`/api/runs/${runId}/stream`);
  let finished = false;
  es.onmessage = (msg) => {
    const ev = JSON.parse(msg.data) as StreamEvent;
    if (ev.stage === "pipeline") {
      finished = true;
      es.close();
    }
    onEvent(ev);
  };
  es.onerror = () => {
    es.close();
    if (!finished) onConnectionError();
  };
  return () => es.close();
}
