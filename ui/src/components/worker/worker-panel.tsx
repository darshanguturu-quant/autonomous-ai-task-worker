import { useCallback, useEffect, useRef, useState } from "react";
import { Check, CircleAlert, LoaderCircle, Play, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface WorkerEvent {
  type: string;
  question?: string;
  candidates?: Array<{ candidate_id: number; filename: string; modified_time: string }>;
  [key: string]: unknown;
}

interface WorkerTask {
  id: string;
  task: string;
  created_at: string;
  status: string;
  approval_needed: boolean;
  events?: WorkerEvent[];
  result?: WorkerEvent | null;
  blocked_reason?: string;
  next_action?: string;
  next_action_label?: string;
}

const INITIAL_TASK_HISTORY_COUNT = 5;
const TASK_HISTORY_INCREMENT = 3;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function eventHeadline(event: WorkerEvent): string {
  if (event.type === "blocked" && typeof event.reason === "string") {
    return `Blocked by policy: ${event.reason}`;
  }
  if (event.type === "clarification_required" && typeof event.question === "string") {
    return event.question;
  }
  if (typeof event.description === "string") return event.description;
  if (typeof event.message === "string") return event.message;
  if (typeof event.summary === "string") return event.summary;
  if (typeof event.action === "string") return event.action.replaceAll("_", " ");
  if (typeof event.thought === "string") return event.thought;
  if (typeof event.error === "string") return event.error;
  return event.type.replaceAll("_", " ");
}

export function WorkerPanel({ onTaskCompleted }: { onTaskCompleted: () => void }) {
  const [goal, setGoal] = useState("");
  const [tasks, setTasks] = useState<WorkerTask[]>([]);
  const [visibleTaskCount, setVisibleTaskCount] = useState(INITIAL_TASK_HISTORY_COUNT);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<WorkerTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const refreshTasks = useCallback(async () => {
    try {
      setTasks(await request<WorkerTask[]>("/api/worker/tasks"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load worker tasks.");
    }
  }, []);

  useEffect(() => {
    void refreshTasks();
    return () => sourceRef.current?.close();
  }, [refreshTasks]);

  const openTask = useCallback(async (id: string) => {
    sourceRef.current?.close();
    setActiveId(id);
    setError(null);
    try {
      const selected = await request<WorkerTask>(`/api/worker/tasks/${id}`);
      setActiveTask(selected);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to open worker task.");
    }
  }, []);

  const streamTask = useCallback((id: string) => {
    sourceRef.current?.close();
    const source = new EventSource(`/api/worker/tasks/${id}/stream`);
    sourceRef.current = source;
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as WorkerEvent;
      setActiveTask((current) => current ? {
        ...current,
        events: [...(current.events ?? []), event],
        status: event.type === "approval_required" ? "awaiting_approval"
          : event.type === "clarification_required" ? "awaiting_clarification"
          : event.type === "completed" ? "completed"
          : event.type === "failed" ? "failed"
          : ["blocked", "unsupported"].includes(event.type) ? event.type : "running",
        approval_needed: event.type === "approval_required",
        result: ["completed", "failed", "blocked"].includes(event.type) ? event : current.result,
      } : current);
      if (["approval_required", "clarification_required", "completed", "failed", "blocked", "unsupported"].includes(event.type)) {
        source.close();
        void refreshTasks();
        if (event.type === "completed") onTaskCompleted();
      }
    };
    source.onerror = () => {
      source.close();
      void refreshTasks();
    };
  }, [onTaskCompleted, refreshTasks]);

  const submitGoal = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (goal.trim().length < 5 || busy) return;
    setBusy(true);
    setError(null);
    sourceRef.current?.close();
    try {
      const created = await request<{ task_id: string }>("/api/worker/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task: goal.trim() }),
      });
      setGoal("");
      setActiveId(created.task_id);
      setActiveTask({
        id: created.task_id, task: goal.trim(), created_at: new Date().toISOString(),
        status: "running", approval_needed: false, events: [],
      });
      await refreshTasks();
      streamTask(created.task_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to start task.");
    } finally {
      setBusy(false);
    }
  };

  const decideApproval = async (approved: boolean) => {
    if (!activeTask) return;
    setBusy(true);
    setError(null);
    sourceRef.current?.close();
    try {
      const result = await request<{ status: string; result?: WorkerEvent }>(
        `/api/worker/tasks/${activeTask.id}/approve`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved }) },
      );
      const updated = await request<WorkerTask>(`/api/worker/tasks/${activeTask.id}`);
      setActiveTask(updated);
      if (result.result) await refreshTasks();
      if (result.status === "completed") onTaskCompleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to record approval.");
    } finally {
      setBusy(false);
    }
  };

  const selectCandidate = async (candidateId: number) => {
    if (!activeTask) return;
    setBusy(true);
    setError(null);
    try {
      await request<{ status: string; result?: WorkerEvent }>(
        `/api/worker/tasks/${activeTask.id}/clarify`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ candidate_id: candidateId }) },
      );
      const updated = await request<WorkerTask>(`/api/worker/tasks/${activeTask.id}`);
      setActiveTask(updated);
      await refreshTasks();
      if (updated.status === "completed") onTaskCompleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to select that invoice.");
    } finally {
      setBusy(false);
    }
  };

  const cancelTask = async () => {
    if (!activeTask) return;
    setBusy(true);
    setError(null);
    try {
      const cancelled = await request<{ status: string }>(
        `/api/worker/tasks/${activeTask.id}/cancel`, { method: "POST" },
      );
      const updated = await request<WorkerTask>(`/api/worker/tasks/${activeTask.id}`);
      setActiveTask(updated);
      await refreshTasks();
      if (cancelled.status === "cancelled") {
        setActiveTask((current) => current ? {
          ...current,
          events: [...(current.events ?? []), {
            type: "cancelled", message: "Task cancelled by user. No further action will be attempted.",
          }],
        } : current);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to cancel task.");
    } finally {
      setBusy(false);
    }
  };

  const events = activeTask?.events ?? [];
  const visibleTasks = tasks.slice(0, visibleTaskCount);

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">Autonomous task worker</CardTitle>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={() => void refreshTasks()} aria-label="Refresh worker tasks">
            <RefreshCw className="size-3.5" /> Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={(event) => void submitGoal(event)} className="space-y-2">
          <label htmlFor="worker-goal" className="text-xs font-medium">Task goal</label>
          <textarea
            id="worker-goal"
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder=""
            maxLength={2000}
            rows={3}
            className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/20"
          />
          <div className="flex items-center justify-between gap-3">
            <Button type="submit" disabled={busy || goal.trim().length < 5}>
              {busy ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-4" />}
              Run task
            </Button>
          </div>
        </form>

        {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">{error}</p>}

        <div className="grid gap-4 border-t border-border pt-4 md:grid-cols-[minmax(180px,0.8fr)_minmax(0,1.6fr)]">
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Task history</h4>
            {tasks.length === 0 ? (
              <p className="rounded-md bg-surface p-3 text-xs text-muted-foreground">No worker tasks yet.</p>
            ) : visibleTasks.map((task) => (
              <button
                type="button"
                key={task.id}
                onClick={() => void openTask(task.id)}
                className={`w-full rounded-md border p-3 text-left transition-colors ${activeId === task.id ? "border-primary/50 bg-primary/5" : "border-border hover:bg-surface"}`}
              >
                <span className="block truncate text-xs font-medium">{task.task}</span>
                <span className="mt-1 block text-[11px] text-muted-foreground">{task.status.replaceAll("_", " ")}</span>
                {task.status === "blocked" && task.blocked_reason && (
                  <span className="mt-1 block line-clamp-2 text-[11px] text-destructive">{task.blocked_reason}</span>
                )}
              </button>
            ))}
            {tasks.length > INITIAL_TASK_HISTORY_COUNT && (
              <div className="flex gap-2 pt-1">
                {visibleTaskCount < tasks.length && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setVisibleTaskCount((count) => Math.min(count + TASK_HISTORY_INCREMENT, tasks.length))}
                  >
                    Show {Math.min(TASK_HISTORY_INCREMENT, tasks.length - visibleTaskCount)} more
                  </Button>
                )}
                {visibleTaskCount > INITIAL_TASK_HISTORY_COUNT && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setVisibleTaskCount(INITIAL_TASK_HISTORY_COUNT)}
                  >
                    Show less
                  </Button>
                )}
              </div>
            )}
          </div>

          <div className="min-w-0 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Execution evidence</h4>
              {activeTask && <span className="rounded-full bg-surface px-2 py-1 text-[11px] capitalize text-muted-foreground">{activeTask.status.replaceAll("_", " ")}</span>}
            </div>
            {!activeTask ? (
              null
            ) : (
              <>
                <div className="rounded-md border border-border bg-card p-3">
                  <p className="mb-2 text-xs leading-relaxed">{activeTask.task}</p>
                  <ol className="max-h-80 divide-y divide-border overflow-y-auto">
                  {events.map((event, index) => (
                    <li key={`${event.type}-${index}`} className="py-2 first:pt-0 last:pb-0">
                      <div className="flex items-center gap-2 text-xs font-medium capitalize">
                        {event.type === "completed" ? <Check className="size-3.5 text-emerald-600" />
                          : ["failed", "blocked", "approval_required"].includes(event.type) ? <CircleAlert className="size-3.5 text-amber-600" />
                          : <span className="size-2 rounded-full bg-primary" />}
                        {event.type.replaceAll("_", " ")}
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{eventHeadline(event)}</p>
                      {(event.result || event.evidence || event.invoice_data) && (
                        <pre className="mt-2 max-h-36 overflow-auto font-mono text-[10px] leading-relaxed text-muted-foreground">
                          {JSON.stringify(event.result ?? event.evidence ?? event.invoice_data, null, 2)}
                        </pre>
                      )}
                      {event.type === "clarification_required" && event.candidates?.map((candidate) => (
                        <Button
                          key={candidate.candidate_id}
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          className="mt-2 mr-2 h-auto min-h-8 whitespace-normal py-1.5 text-left"
                          onClick={() => void selectCandidate(candidate.candidate_id)}
                        >
                          {candidate.filename} · {new Date(candidate.modified_time).toLocaleString()}
                        </Button>
                      ))}
                    </li>
                  ))}
                    {events.length === 0 && <li className="py-2 text-xs text-muted-foreground">Waiting for worker events…</li>}
                  </ol>
                </div>
                {activeTask.approval_needed && (
                  <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                    <p className="mb-3 text-xs font-medium">Human review required. Approval permits recording the item, but does not override a rules-engine rejection or approve it for payment.</p>
                    <div className="flex gap-2">
                      <Button type="button" size="sm" variant="success" disabled={busy} onClick={() => void decideApproval(true)}><Check className="size-3.5" /> Approve recording</Button>
                      <Button type="button" size="sm" variant="destructive" disabled={busy} onClick={() => void decideApproval(false)}><X className="size-3.5" /> Reject</Button>
                    </div>
                  </div>
                )}
                {activeTask.status === "blocked" && (
                  <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
                    <p className="mb-2 text-xs font-medium">Blocked: {activeTask.blocked_reason ?? String(activeTask.result?.reason ?? "The policy rejected this action.")}</p>
                    <p className="mb-3 text-[11px] text-muted-foreground">No override is available for a deterministic rejection. Cancel this task and submit a corrected invoice or request.</p>
                    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void cancelTask()}>
                      Cancel blocked task
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}