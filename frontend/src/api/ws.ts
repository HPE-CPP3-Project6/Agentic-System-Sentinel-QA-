import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { wsUrl } from "./client";
import { queryKeys } from "./hooks";
import type { PhaseName, RunStatus, VerdictRecord, WsEvent } from "./types";
import { useRunStreamStore } from "@/stores/runStreamStore";
import { useUiStore } from "@/stores/uiStore";

const MAX_LOG_LINES = 5000;

function parseEvent(raw: MessageEvent<string>): WsEvent | null {
  try {
    return JSON.parse(raw.data) as WsEvent;
  } catch {
    return null;
  }
}

export function useRunStream(runId: string | undefined) {
  const qc = useQueryClient();
  const setWsStatus = useUiStore((s) => s.setWsStatus);
  const {
    reset,
    appendLog,
    setPhases,
    upsertPhase,
    addVerdict,
    setRunStatus,
    setFailure,
  } = useRunStreamStore();
  const lastSeq = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!runId) return;

    reset(runId);
    lastSeq.current = 0;

    let closed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (closed) return;
      setWsStatus("connecting");
      const url = wsUrl(
        `/ws/runs/${runId}${lastSeq.current ? `?after_seq=${lastSeq.current}` : ""}`,
      );
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => setWsStatus("connected");
      ws.onclose = () => {
        setWsStatus("disconnected");
        if (!closed) {
          reconnectTimer = setTimeout(connect, 2000);
        }
      };
      ws.onerror = () => setWsStatus("error");

      ws.onmessage = (event) => {
        const evt = parseEvent(event);
        if (!evt || evt.run_id !== runId) return;
        lastSeq.current = Math.max(lastSeq.current, evt.seq);

        switch (evt.type) {
          case "phase_started":
            upsertPhase({
              phase: evt.phase,
              status: "running",
              started_at: evt.ts,
            });
            setRunStatus("running");
            break;
          case "phase_completed":
            upsertPhase({
              phase: evt.phase,
              status: "completed",
              duration_ms: evt.duration_ms,
            });
            break;
          case "pytest_stdout":
            appendLog(evt.line, MAX_LOG_LINES);
            break;
          case "verdict_decided":
            addVerdict({
              test_id: evt.test_id,
              status: evt.status,
              verdict: evt.verdict,
              verdict_confidence: evt.verdict_confidence,
              duration_ms: evt.duration_ms,
              exploit_target: evt.exploit_target,
            } satisfies VerdictRecord);
            break;
          case "run_paused":
            setRunStatus("paused");
            break;
          case "run_completed":
            setRunStatus("completed");
            qc.invalidateQueries({ queryKey: queryKeys.run(runId) });
            qc.invalidateQueries({ queryKey: queryKeys.artifact(runId) });
            break;
          case "run_failed":
            setRunStatus("failed");
            setFailure(evt.code, evt.message, evt.phase);
            upsertPhase({
              phase: evt.phase ?? ("executor" as PhaseName),
              status: "failed",
            });
            break;
        }
      };
    };

    connect();

    return () => {
      closed = true;
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [
    runId,
    reset,
    appendLog,
    setPhases,
    upsertPhase,
    addVerdict,
    setRunStatus,
    setFailure,
    setWsStatus,
    qc,
  ]);
}

export function useRunStreamStatus(): RunStatus | "idle" {
  return useRunStreamStore((s) => s.runStatus);
}
