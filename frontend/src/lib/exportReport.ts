import type { ProjectState, SurfaceBinding, VerdictRecord } from "@/api/types";
import { computeSummary } from "./reportSummary";

// xlsx + jspdf are heavy (~1 MB combined) and only needed on an explicit export
// click, so they are dynamically imported inside each function to keep them out
// of the Report tab's initial chunk.

function fileStem(a: ProjectState, runId?: string): string {
  const story = (a.story_id || "report").replace(/[^A-Za-z0-9_-]/g, "_");
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  return `sentinel_${story}_${runId ?? ""}_${stamp}`.replace(/_+/g, "_");
}

function findingsRows(a: ProjectState): Record<string, string | number>[] {
  return (a.execution_logs ?? []).map((l: VerdictRecord) => ({
    test_id: l.test_id,
    title: l.title ?? "",
    category: l.category ?? "",
    technique: l.technique ?? "",
    status: l.status,
    verdict: l.verdict ?? "",
    confidence: l.verdict_confidence ?? "",
    duration_ms: l.duration_ms ?? "",
    evidence: l.stderr_excerpt ?? (l.verdict_evidence ?? []).join("; "),
  }));
}

function surfaceRows(a: ProjectState): Record<string, string>[] {
  return Object.values((a.surface_map ?? {}) as Record<string, SurfaceBinding>).map((b) => ({
    requirement: b.req_id,
    state: b.state,
    threat_class: b.threat_class ?? "",
    defense_kind: b.defense_kind ?? "",
    endpoints: (b.backend_endpoints ?? []).map((e) => `${e.method} ${e.path}`).join(", "),
    confidence: b.confidence ?? "",
  }));
}

function summaryRows(a: ProjectState): Record<string, string | number>[] {
  const s = computeSummary(a);
  const rows: Record<string, string | number>[] = [
    { metric: "Story", value: a.story_title ?? a.story_id ?? "—" },
    { metric: "Pipeline mode", value: String(a.pipeline_mode) },
    { metric: "Run validity", value: a.run_validity },
    { metric: "Coverage quality", value: a.coverage_quality ?? a.suite_quality ?? "—" },
    { metric: "Total tests", value: s.total },
    { metric: "Passed", value: s.passed },
    { metric: "Failed", value: s.failed },
    { metric: "Errored", value: s.error },
    { metric: "Skipped", value: s.skipped },
    { metric: "Success %", value: `${s.successPct}%` },
  ];
  if (s.resiliencePct != null) rows.push({ metric: "Resilience %", value: `${Math.round(s.resiliencePct)}%` });
  if (s.vulnerable != null) rows.push({ metric: "Vulnerabilities", value: s.vulnerable });
  return rows;
}

/** Real .xlsx workbook (Summary / Findings / Surface Map sheets). */
export async function exportXlsx(a: ProjectState, runId?: string): Promise<void> {
  const XLSX = await import("xlsx");
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(summaryRows(a)), "Summary");
  const findings = findingsRows(a);
  if (findings.length) {
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(findings), "Findings");
  }
  const surfaces = surfaceRows(a);
  if (surfaces.length) {
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(surfaces), "Surface Map");
  }
  const techniques = a.test_suite_summary?.by_technique;
  if (techniques) {
    const techRows = Object.entries(techniques).map(([t, v]) => ({
      technique: t,
      planned: (v as { planned?: number }).planned ?? 0,
      executed: (v as { executed?: number }).executed ?? 0,
    }));
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(techRows), "Techniques");
  }
  XLSX.writeFile(wb, `${fileStem(a, runId)}.xlsx`);
}

/** Real downloadable .pdf (header + summary + findings table). */
export async function exportPdf(a: ProjectState, runId?: string): Promise<void> {
  const [{ jsPDF }, { default: autoTable }] = await Promise.all([
    import("jspdf"),
    import("jspdf-autotable"),
  ]);
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const left = 40;
  let y = 48;

  doc.setFontSize(16);
  doc.text("Sentinel-QA — Test Attestation Report", left, y);
  y += 20;
  doc.setFontSize(10);
  doc.setTextColor(110);
  doc.text(
    `${a.story_title ?? a.story_id ?? "Story"}  ·  ${String(a.pipeline_mode).toUpperCase()}  ·  run_validity: ${a.run_validity}`,
    left,
    y,
  );
  doc.setTextColor(20);
  y += 16;

  autoTable(doc, {
    startY: y,
    head: [["Metric", "Value"]],
    body: summaryRows(a).map((r) => [String(r.metric), String(r.value)]),
    theme: "striped",
    headStyles: { fillColor: [37, 99, 235] },
    styles: { fontSize: 9 },
    margin: { left, right: left },
  });

  const findings = findingsRows(a);
  if (findings.length) {
    autoTable(doc, {
      head: [["Test", "Technique", "Status", "Verdict", "Evidence"]],
      body: findings.map((f) => [
        String(f.test_id),
        String(f.technique),
        String(f.status),
        String(f.verdict),
        String(f.evidence).slice(0, 80),
      ]),
      theme: "grid",
      headStyles: { fillColor: [37, 99, 235] },
      styles: { fontSize: 7, cellPadding: 3 },
      margin: { left, right: left },
    });
  }

  doc.save(`${fileStem(a, runId)}.pdf`);
}
