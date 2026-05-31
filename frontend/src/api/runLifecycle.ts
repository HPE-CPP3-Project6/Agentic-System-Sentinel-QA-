import type { PhaseName, RunStatus, WorkspaceTab } from "./types";

const PHASE_ORDER: PhaseName[] = [
  "critic",
  "surface_resolver",
  "generator",
  "security_compiler",
  "executor",
];

export function isRunInFlight(status?: RunStatus): boolean {
  return status === "queued" || status === "running";
}

/** Artifact endpoint returns data when the run is paused at a gate or finished. */
export function isArtifactReady(status?: RunStatus): boolean {
  return status === "paused" || status === "completed";
}

/** Report tab is meaningful only after executor finishes. */
export function isReportReady(status?: RunStatus): boolean {
  return status === "completed";
}

export function phaseIndex(phase: PhaseName): number {
  return PHASE_ORDER.indexOf(phase);
}

function phaseIdx(currentPhase?: PhaseName | null): number {
  if (!currentPhase) return -1;
  return phaseIndex(currentPhase);
}

/** Surface map available — paused at/after surface_resolver, or running later phases. */
export function isSurfaceGateDone(
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): boolean {
  if (status === "completed") return true;
  const idx = phaseIdx(currentPhase);
  const surfaceIdx = phaseIndex("surface_resolver");
  if (idx < 0) return false;
  if (status === "paused") return idx >= surfaceIdx;
  if (status === "running") return idx > surfaceIdx;
  return false;
}

/** Test suite available — paused at/after security_compiler, or executor running. */
export function isScenariosGateDone(
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): boolean {
  if (status === "completed") return true;
  const idx = phaseIdx(currentPhase);
  const compilerIdx = phaseIndex("security_compiler");
  if (idx < 0) return false;
  if (status === "paused") return idx >= compilerIdx;
  if (status === "running" && currentPhase === "executor") return true;
  return false;
}

/** Pytest script file on disk — same gate as scenarios output. */
export function isScriptReady(
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): boolean {
  return isScenariosGateDone(status, currentPhase);
}

/** @deprecated use isScenariosGateDone */
export function isScenariosReady(
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): boolean {
  return isScenariosGateDone(status, currentPhase);
}

export function isSurfaceReady(
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): boolean {
  return isSurfaceGateDone(status, currentPhase);
}

export function canGenerateTests(
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): boolean {
  return status === "paused" && currentPhase === "surface_resolver";
}

/** Script compiled but executor not started yet (regular flow gate after Scripts). */
export function canStartExecution(
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): boolean {
  return status === "paused" && currentPhase === "security_compiler";
}

/** Run tab — script exists and user may start (or is executing). */
export function isRunGateDone(
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): boolean {
  if (status === "completed") return true;
  if (status === "running" && currentPhase === "executor") return true;
  return isScriptReady(status, currentPhase);
}

/** Whether the user may open this tab in the stepper. */
export function isTabAccessible(
  tab: WorkspaceTab,
  runId: string | undefined,
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): boolean {
  if (tab === "input") return true;
  if (!runId) return false;
  switch (tab) {
    case "surface":
      return true;
    case "scenarios":
      if (isScenariosGateDone(status, currentPhase)) return true;
      // Advancing from surface pause → generator (status queued, phase still surface_resolver)
      if (status === "queued" && currentPhase === "surface_resolver") return true;
      if (
        status === "running" &&
        (currentPhase === "generator" || currentPhase === "security_compiler")
      ) {
        return true;
      }
      return false;
    case "scripts":
      if (isScriptReady(status, currentPhase)) return true;
      if (
        status === "running" &&
        currentPhase === "security_compiler"
      ) {
        return true;
      }
      return false;
    case "run":
      if (isRunGateDone(status, currentPhase)) return true;
      // Starting executor after Scripts → Continue
      if (status === "queued" && currentPhase === "security_compiler") return true;
      if (status === "running" && currentPhase === "executor") return true;
      return false;
    case "report":
      return isReportReady(status);
    default:
      return false;
  }
}

export function unlockedTabsForRun(
  runId: string | undefined,
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): Set<WorkspaceTab> {
  const tabs = new Set<WorkspaceTab>(["input"]);
  if (!runId) return tabs;
  if (status === "completed" || status === "failed") {
    tabs.add("surface");
    tabs.add("scenarios");
    tabs.add("scripts");
    tabs.add("run");
    tabs.add("report");
    return tabs;
  }
  tabs.add("surface");
  if (isTabAccessible("scenarios", runId, status, currentPhase)) tabs.add("scenarios");
  if (isTabAccessible("scripts", runId, status, currentPhase)) tabs.add("scripts");
  if (isTabAccessible("run", runId, status, currentPhase)) tabs.add("run");
  if (isTabAccessible("report", runId, status, currentPhase)) tabs.add("report");
  return tabs;
}

function isCompilerPhase(phase?: PhaseName | null): boolean {
  return phase === "security_compiler" || phase === "compiler";
}

/** Best tab for the run's current backend state. */
export function tabForRun(
  status?: RunStatus,
  currentPhase?: PhaseName | null,
): WorkspaceTab {
  if (isReportReady(status)) return "report";
  if (status === "running" || status === "queued") {
    if (currentPhase === "executor") return "run";
    if (isCompilerPhase(currentPhase)) return "scripts";
    if (currentPhase === "generator") return "scenarios";
    return "surface";
  }
  if (status === "paused") {
    if (isCompilerPhase(currentPhase)) return "scripts";
    if (currentPhase === "surface_resolver") return "surface";
    if (isSurfaceGateDone(status, currentPhase)) return "surface";
  }
  if (status === "failed") {
    if (currentPhase === "executor") return "run";
    if (isCompilerPhase(currentPhase)) return "scripts";
    if (isScenariosGateDone(status, currentPhase)) return "scenarios";
    if (isSurfaceGateDone(status, currentPhase)) return "surface";
  }
  return "input";
}

export { PHASE_ORDER };
