import { useEffect } from "react";
import { useRunStreamStore } from "@/stores/runStreamStore";

/** Simulates WS events when MSW is active (no real WebSocket backend). */
export function useMockRunStream(runId: string | undefined) {
  const { reset, appendLog, upsertPhase, addVerdict, setRunStatus } =
    useRunStreamStore();

  useEffect(() => {
    if (!runId || import.meta.env.VITE_USE_MSW !== "true") return;

    reset(runId);
    setRunStatus("running");

    const phases = [
      "critic",
      "surface_resolver",
      "generator",
      "compiler",
      "executor",
    ] as const;

    let cancelled = false;
    let step = 0;

    const tick = () => {
      if (cancelled || step >= phases.length) {
        if (!cancelled) {
          appendLog("tests/test_sentinel_api_generated.py::TC-REQ-001-01 PASSED", 5000);
          addVerdict({
            test_id: "TC-REQ-001-01",
            status: "passed",
            verdict: "resilient",
            verdict_confidence: "high",
            duration_ms: 142,
            exploit_target: "A03:2021",
          });
          setRunStatus("completed");
        }
        return;
      }

      const phase = phases[step];
      upsertPhase({ phase, status: "running" });
      appendLog(`[${phase}] phase started`, 5000);

      setTimeout(() => {
        if (cancelled) return;
        upsertPhase({
          phase,
          status: "completed",
          duration_ms: 1200 + step * 800,
        });
        appendLog(`[${phase}] phase completed`, 5000);
        step += 1;
        tick();
      }, 600);
    };

    tick();
    return () => {
      cancelled = true;
    };
  }, [runId, reset, appendLog, upsertPhase, addVerdict, setRunStatus]);
}
