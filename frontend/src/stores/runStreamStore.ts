import { create } from "zustand";
import type { PhaseName, RunStatus, VerdictRecord } from "@/api/types";

export interface StreamPhase {
  phase: PhaseName;
  status: "pending" | "running" | "completed" | "failed";
  duration_ms?: number;
  started_at?: string;
}

interface RunStreamState {
  runId: string | null;
  runStatus: RunStatus | "idle";
  phases: StreamPhase[];
  logLines: string[];
  verdicts: VerdictRecord[];
  failureCode: string | null;
  failureMessage: string | null;
  reset: (runId: string) => void;
  appendLog: (line: string, max: number) => void;
  setPhases: (phases: StreamPhase[]) => void;
  upsertPhase: (phase: StreamPhase) => void;
  addVerdict: (verdict: VerdictRecord) => void;
  setRunStatus: (status: RunStatus | "idle") => void;
  setFailure: (code: string, message: string, phase?: PhaseName) => void;
}

const DEFAULT_PHASES: PhaseName[] = [
  "critic",
  "surface_resolver",
  "generator",
  "security_compiler",
  "executor",
];

export const useRunStreamStore = create<RunStreamState>((set) => ({
  runId: null,
  runStatus: "idle",
  phases: DEFAULT_PHASES.map((phase) => ({ phase, status: "pending" })),
  logLines: [],
  verdicts: [],
  failureCode: null,
  failureMessage: null,
  reset: (runId) =>
    set({
      runId,
      runStatus: "idle",
      phases: DEFAULT_PHASES.map((phase) => ({ phase, status: "pending" })),
      logLines: [],
      verdicts: [],
      failureCode: null,
      failureMessage: null,
    }),
  appendLog: (line, max) =>
    set((s) => {
      const next = [...s.logLines, line];
      if (next.length > max) next.splice(0, next.length - max);
      return { logLines: next };
    }),
  setPhases: (phases) => set({ phases }),
  upsertPhase: (phase) =>
    set((s) => {
      const idx = s.phases.findIndex((p) => p.phase === phase.phase);
      if (idx === -1) return { phases: [...s.phases, phase] };
      const phases = [...s.phases];
      phases[idx] = { ...phases[idx], ...phase };
      return { phases };
    }),
  addVerdict: (verdict) =>
    set((s) => {
      const idx = s.verdicts.findIndex((v) => v.test_id === verdict.test_id);
      if (idx === -1) return { verdicts: [...s.verdicts, verdict] };
      const verdicts = [...s.verdicts];
      verdicts[idx] = verdict;
      return { verdicts };
    }),
  setRunStatus: (runStatus) => set({ runStatus }),
  setFailure: (failureCode, failureMessage) =>
    set({ failureCode, failureMessage, runStatus: "failed" }),
}));
