import { useEffect, useReducer, useRef } from "react";
import { openRunStream } from "@/lib/api";
import type { RunTrace, StageName, StreamEvent } from "@/lib/types";
import { STAGE_ORDER } from "@/lib/types";

export interface StageState {
  status: "idle" | "running" | "success" | "error";
  output?: Record<string, unknown>;
  durationMs?: number;
}

export interface RunStreamState {
  stages: Record<StageName, StageState>;
  final: { status: "completed"; result: RunTrace } | { status: "failed"; error: string } | null;
  isReplay: boolean;
  connectionLost: boolean;
}

const initial = (): RunStreamState => ({
  stages: {
    extract: { status: "idle" },
    guardrails: { status: "idle" },
    validate: { status: "idle" },
    match: { status: "idle" },
    decide: { status: "idle" },
  },
  final: null,
  isReplay: false,
  connectionLost: false,
});

type Action =
  | { type: "reset" }
  | { type: "event"; ev: StreamEvent }
  | { type: "connection-lost" };

function reducer(state: RunStreamState, action: Action): RunStreamState {
  switch (action.type) {
    case "reset":
      return initial();
    case "connection-lost":
      return { ...state, connectionLost: true };
    case "event": {
      const ev = action.ev;
      const isReplay = state.isReplay || Boolean(ev.replay);
      if (ev.stage === "pipeline") {
        if (ev.status === "failed") {
          // mark whichever stage was running as the failure point
          const stages = { ...state.stages };
          for (const name of STAGE_ORDER) {
            if (stages[name].status === "running") stages[name] = { status: "error" };
          }
          return {
            ...state, stages, isReplay,
            final: { status: "failed", error: ev.error ?? "unknown error" },
          };
        }
        // On replay the per-stage events carry outputs; the final event carries
        // the authoritative result either way.
        return { ...state, isReplay, final: { status: "completed", result: ev.result! } };
      }
      const name = ev.stage as StageName;
      const stages = { ...state.stages };
      stages[name] =
        ev.status === "running"
          ? { status: "running" }
          : { status: "success", output: ev.output, durationMs: ev.duration_ms };
      // Replays send only `completed` events - synthesize the running order so
      // the node transitions still read correctly.
      return { ...state, stages, isReplay };
    }
  }
}

/**
 * Consume the run's SSE stream with a paced reveal: events are queued and
 * revealed at most one per REVEAL_MS so stage transitions are visible even
 * when the backend finishes instantly (e.g. replays, text-native extracts).
 * Pacing only affects presentation - every event is a real execution record.
 */
export function useRunStream(runId: number | null): RunStreamState {
  const [state, dispatch] = useReducer(reducer, undefined, initial);
  const queueRef = useRef<StreamEvent[]>([]);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    dispatch({ type: "reset" });
    queueRef.current = [];
    if (timerRef.current) window.clearInterval(timerRef.current);
    if (runId == null) return;

    const REVEAL_MS = 260;
    timerRef.current = window.setInterval(() => {
      const next = queueRef.current.shift();
      if (next) dispatch({ type: "event", ev: next });
    }, REVEAL_MS);

    const close = openRunStream(
      runId,
      (ev) => queueRef.current.push(ev),
      () => dispatch({ type: "connection-lost" }),
    );
    return () => {
      close();
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [runId]);

  return state;
}
