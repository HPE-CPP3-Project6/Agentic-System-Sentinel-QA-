import type { jsPDF } from "jspdf";
import type { UserOptions } from "jspdf-autotable";
import type {
  ProjectState,
  SuggestedPatch,
  SurfaceBinding,
  VerdictRecord,
} from "@/api/types";
import { computeSummary } from "./reportSummary";
import {
  ATTESTATION_MODE_LABELS,
  CATEGORY_LABELS,
  COVERAGE_QUALITY_LABELS,
  DEFENSE_KIND_LABELS,
  RUN_VALIDITY_LABELS,
  STATUS_LABELS,
  SURFACE_STATE_LABELS,
  TECHNIQUE_LABELS,
  THREAT_CLASS_LABELS,
  VERDICT_LABELS,
  humanize,
  labelText,
  lookupLabel,
} from "@/lib/labels";

// xlsx + jspdf are heavy (~1 MB combined) and only needed on an explicit export
// click, so they are dynamically imported inside each function to keep them out
// of the Report tab's initial chunk.

// ── Palette (print-friendly) ─────────────────────────────────────────────────
type RGB = [number, number, number];
const NAVY: RGB = [12, 35, 64];
const PRIMARY: RGB = [0, 92, 185];
const SUCCESS: RGB = [30, 120, 60];
const DANGER: RGB = [193, 39, 45];
const CAUTION: RGB = [166, 116, 0];
const MUTED: RGB = [110, 118, 128];
const BORDER: RGB = [214, 218, 224];
const SURFACE: RGB = [246, 247, 249];
const WHITE: RGB = [255, 255, 255];
const INK: RGB = [26, 35, 50];
const SUBTLE: RGB = [200, 214, 235];

type AutoTableFn = (doc: jsPDF, options: UserOptions) => void;

const M = 40; // page margin

const fill = (d: jsPDF, c: RGB) => d.setFillColor(c[0], c[1], c[2]);
const ink = (d: jsPDF, c: RGB) => d.setTextColor(c[0], c[1], c[2]);
const stroke = (d: jsPDF, c: RGB) => d.setDrawColor(c[0], c[1], c[2]);
const mix = (a: RGB, b: RGB, t: number): RGB => [
  Math.round(a[0] * (1 - t) + b[0] * t),
  Math.round(a[1] * (1 - t) + b[1] * t),
  Math.round(a[2] * (1 - t) + b[2] * t),
];
const trunc = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const pageH = (d: jsPDF) => d.internal.pageSize.getHeight();
const pageW = (d: jsPDF) => d.internal.pageSize.getWidth();

function isPre(a: ProjectState): boolean {
  return String(a.pipeline_mode).toLowerCase() === "pre_code";
}
function validityColor(v: string): RGB {
  if (v === "OK") return SUCCESS;
  if (v === "DESIGN_ONLY") return PRIMARY;
  if (v === "TARGET_UNREACHABLE") return DANGER;
  return CAUTION;
}

function fileStem(a: ProjectState, runId?: string): string {
  const story = (a.story_id || "report").replace(/[^A-Za-z0-9_-]/g, "_");
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  return `sentinel_${story}_${runId ?? ""}_${stamp}`.replace(/_+/g, "_");
}

// ── PDF layout helpers ───────────────────────────────────────────────────────

function afterTable(doc: jsPDF, fallback: number): number {
  const lat = (doc as unknown as { lastAutoTable?: { finalY?: number } }).lastAutoTable;
  return (lat?.finalY ?? fallback) + 14;
}

function ensureSpace(doc: jsPDF, y: number, needed: number): number {
  if (y + needed > pageH(doc) - 46) {
    doc.addPage();
    return 56;
  }
  return y;
}

function sectionHeading(doc: jsPDF, y0: number, title: string): number {
  const y = ensureSpace(doc, y0, 64);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(11.5);
  ink(doc, NAVY);
  doc.text(title.toUpperCase(), M, y);
  stroke(doc, PRIMARY);
  doc.setLineWidth(1.4);
  doc.line(M, y + 5, pageW(doc) - M, y + 5);
  doc.setFont("helvetica", "normal");
  return y + 20;
}

function table(doc: jsPDF, at: AutoTableFn, opts: UserOptions): number {
  at(doc, {
    theme: "grid",
    headStyles: { fillColor: NAVY, textColor: WHITE, fontStyle: "bold", fontSize: 8, cellPadding: 4 },
    bodyStyles: { fontSize: 7.5, cellPadding: 4, textColor: INK },
    alternateRowStyles: { fillColor: SURFACE },
    styles: { lineColor: BORDER, lineWidth: 0.4, overflow: "linebreak" },
    margin: { left: M, right: M, top: 46, bottom: 44 },
    ...opts,
  });
  return afterTable(doc, 0);
}

function kpiCards(
  doc: jsPDF,
  y0: number,
  cards: { label: string; value: string; color?: RGB }[],
): number {
  const ch = 48;
  const y = ensureSpace(doc, y0, ch + 16);
  const totalW = pageW(doc) - M * 2;
  const gap = 8;
  const cw = (totalW - gap * (cards.length - 1)) / cards.length;
  cards.forEach((c, i) => {
    const cx = M + i * (cw + gap);
    fill(doc, SURFACE);
    stroke(doc, BORDER);
    doc.setLineWidth(0.6);
    doc.roundedRect(cx, y, cw, ch, 3, 3, "FD");
    fill(doc, c.color ?? PRIMARY);
    doc.rect(cx, y, cw, 2.6, "F");
    ink(doc, c.color ?? INK);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(17);
    doc.text(c.value, cx + cw / 2, y + 27, { align: "center" });
    ink(doc, MUTED);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7);
    doc.text(c.label.toUpperCase(), cx + cw / 2, y + 40, { align: "center", maxWidth: cw - 6 });
  });
  return y + ch + 14;
}

function axisCards(doc: jsPDF, y0: number, a: ProjectState): number {
  const ch = 62;
  const y = ensureSpace(doc, y0, ch + 14);
  const totalW = pageW(doc) - M * 2;
  const gap = 10;
  const cw = (totalW - gap) / 2;
  const validity = lookupLabel(RUN_VALIDITY_LABELS, a.run_validity);
  const cq = a.coverage_quality ?? a.suite_quality;
  const coverage = lookupLabel(COVERAGE_QUALITY_LABELS, cq ?? "");
  const items = [
    { kicker: "Run validity", label: validity.label, blurb: validity.blurb, color: validityColor(a.run_validity) },
    { kicker: "Coverage quality", label: cq ? coverage.label : "—", blurb: coverage.blurb, color: PRIMARY },
  ];
  items.forEach((it, i) => {
    const cx = M + i * (cw + gap);
    fill(doc, WHITE);
    stroke(doc, BORDER);
    doc.setLineWidth(0.6);
    doc.roundedRect(cx, y, cw, ch, 3, 3, "FD");
    fill(doc, it.color);
    doc.rect(cx, y, 3, ch, "F");
    ink(doc, MUTED);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(7);
    doc.text(it.kicker.toUpperCase(), cx + 12, y + 16);
    ink(doc, it.color);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(13);
    doc.text(trunc(it.label, 34), cx + 12, y + 33);
    ink(doc, MUTED);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7.5);
    const lines = doc.splitTextToSize(it.blurb, cw - 22) as string[];
    doc.text(lines.slice(0, 2), cx + 12, y + 47);
  });
  return y + ch + 14;
}

function callout(doc: jsPDF, y0: number, text: string, color: RGB): number {
  const w = pageW(doc) - M * 2;
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8.5);
  const lines = doc.splitTextToSize(text, w - 24) as string[];
  const h = 12 + lines.length * 11;
  const y = ensureSpace(doc, y0, h + 12);
  fill(doc, mix(color, WHITE, 0.9));
  stroke(doc, color);
  doc.setLineWidth(0.6);
  doc.roundedRect(M, y, w, h, 2, 2, "FD");
  fill(doc, color);
  doc.rect(M, y, 3, h, "F");
  ink(doc, INK);
  doc.text(lines, M + 12, y + 14);
  return y + h + 14;
}

function coverBand(doc: jsPDF, a: ProjectState, runId: string | undefined, pct?: number): void {
  const W = pageW(doc);
  const bandH = 116;
  fill(doc, NAVY);
  doc.rect(0, 0, W, bandH, "F");
  fill(doc, PRIMARY);
  doc.rect(0, bandH, W, 3, "F");
  ink(doc, SUBTLE);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(8.5);
  doc.text("SENTINEL-QA", M, 30);
  ink(doc, WHITE);
  doc.setFontSize(19);
  doc.text("Security Attestation Report", M, 54);
  ink(doc, SUBTLE);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(10.5);
  doc.text(trunc(String(a.story_title ?? a.story_id ?? "Story"), 62), M, 74);
  doc.setFontSize(8);
  doc.text(
    `${String(a.pipeline_mode).toUpperCase()}   ·   Run ${runId ?? "—"}   ·   Generated ${new Date().toLocaleString()}`,
    M,
    92,
  );
  // right verdict block
  const pre = isPre(a);
  ink(doc, WHITE);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(30);
  doc.text(pre ? "DESIGN" : pct != null ? `${Math.round(pct)}%` : "N/A", W - M, 52, { align: "right" });
  ink(doc, SUBTLE);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.text(pre ? "design artifact" : "resilient", W - M, 66, { align: "right" });
  const vlabel = labelText(RUN_VALIDITY_LABELS, a.run_validity).toUpperCase();
  doc.setFont("helvetica", "bold");
  doc.setFontSize(7.5);
  const tw = doc.getTextWidth(vlabel) + 16;
  fill(doc, validityColor(a.run_validity));
  doc.roundedRect(W - M - tw, 78, tw, 15, 7.5, 7.5, "F");
  ink(doc, WHITE);
  doc.text(vlabel, W - M - tw / 2, 88, { align: "center" });
}

function addChrome(doc: jsPDF, a: ProjectState): void {
  const W = pageW(doc);
  const H = pageH(doc);
  const total = doc.getNumberOfPages();
  const story = trunc(String(a.story_title ?? a.story_id ?? ""), 50);
  for (let i = 1; i <= total; i++) {
    doc.setPage(i);
    if (i > 1) {
      ink(doc, MUTED);
      doc.setFont("helvetica", "normal");
      doc.setFontSize(7.5);
      doc.text("SENTINEL-QA · Security Attestation Report", M, 26);
      doc.text(story, W - M, 26, { align: "right" });
      stroke(doc, BORDER);
      doc.setLineWidth(0.5);
      doc.line(M, 32, W - M, 32);
    }
    stroke(doc, BORDER);
    doc.setLineWidth(0.5);
    doc.line(M, H - 32, W - M, H - 32);
    ink(doc, MUTED);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7.5);
    doc.text("Sentinel-QA · Confidential", M, H - 20);
    doc.text(`Page ${i} of ${total}`, W - M, H - 20, { align: "right" });
  }
}

// ── PDF ──────────────────────────────────────────────────────────────────────

/** Professional multi-section attestation report (.pdf). */
export async function exportPdf(a: ProjectState, runId?: string): Promise<void> {
  const [{ jsPDF }, { default: autoTable }] = await Promise.all([
    import("jspdf"),
    import("jspdf-autotable"),
  ]);
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const at = autoTable as unknown as AutoTableFn;
  const pre = isPre(a);
  const s = computeSummary(a);
  const posture = a.security_posture;
  const pct = posture?.resilience_pct ?? a.resilience_pct ?? undefined;

  coverBand(doc, a, runId, pct);
  let y = 138;

  // ── Executive summary ──
  y = sectionHeading(doc, y, "Executive Summary");
  if (pre) {
    const ds = a.design_summary;
    y = kpiCards(doc, y, [
      { label: "Requirements", value: String(ds?.requirements_total ?? "—") },
      { label: "With contract", value: String(ds?.requirements_with_contract ?? 0), color: SUCCESS },
      { label: "Contracts", value: String(ds?.contracts_total ?? 0) },
      { label: "Checklist items", value: String(ds?.checklist_total ?? 0) },
    ]);
  } else {
    y = kpiCards(doc, y, [
      { label: "Resilience", value: pct != null ? `${Math.round(pct)}%` : "—", color: SUCCESS },
      { label: "Tests", value: String(s.total) },
      { label: "Passed", value: String(s.passed), color: SUCCESS },
      { label: "Failed", value: String(s.failed), color: s.failed ? DANGER : MUTED },
      { label: "Vulnerable", value: String(posture?.vulnerable ?? 0), color: posture?.vulnerable ? DANGER : MUTED },
      { label: "Unclassified", value: String(posture?.unclassified ?? 0), color: posture?.unclassified ? CAUTION : MUTED },
    ]);
  }
  y = axisCards(doc, y, a);
  const evidence =
    (a.metadata?.run_validity_evidence as { reason?: string } | undefined)?.reason ??
    a.attestation_banner ??
    undefined;
  if (evidence) y = callout(doc, y, String(evidence), validityColor(a.run_validity));

  // ── Security posture (POST_CODE) ──
  if (!pre && posture) {
    y = sectionHeading(doc, y, "Security Posture — OWASP Exploit Targets");
    const byTarget = posture.by_exploit_target ?? {};
    const rows = Object.entries(byTarget).map(([k, v]) => [
      humanize(k),
      String(v.attempted ?? 0),
      String(v.resilient ?? 0),
      String(v.vulnerable ?? 0),
      String(v.skipped ?? 0),
      String(v.unclassified ?? 0),
    ]);
    if (rows.length) {
      y = table(doc, at, {
        startY: y,
        head: [["OWASP exploit target", "Attempted", "Resilient", "Vulnerable", "Skipped", "Unclassified"]],
        body: rows,
        columnStyles: {
          0: { cellWidth: 190 },
          1: { halign: "center" },
          2: { halign: "center" },
          3: { halign: "center" },
          4: { halign: "center" },
          5: { halign: "center" },
        },
        didParseCell: (d) => {
          if (d.section !== "body") return;
          if (d.column.index === 2 && Number(d.cell.raw) > 0) d.cell.styles.textColor = SUCCESS;
          if (d.column.index === 3 && Number(d.cell.raw) > 0) {
            d.cell.styles.textColor = DANGER;
            d.cell.styles.fontStyle = "bold";
          }
          if (d.column.index === 5 && Number(d.cell.raw) > 0) d.cell.styles.textColor = CAUTION;
        },
      });
    } else {
      ink(doc, MUTED);
      doc.setFontSize(8.5);
      doc.text("No per-target posture breakdown available.", M, y);
      y += 16;
    }
  }

  // ── Findings ──
  if (!pre && (a.execution_logs?.length ?? 0) > 0) {
    y = sectionHeading(doc, y, "Findings");
    const rows = (a.execution_logs ?? []).map((l: VerdictRecord) => [
      l.test_id,
      trunc(l.title ?? "", 42),
      l.technique
        ? labelText(TECHNIQUE_LABELS, l.technique)
        : l.category
          ? labelText(CATEGORY_LABELS, l.category)
          : "—",
      l.exploit_target ? humanize(l.exploit_target) : "—",
      labelText(STATUS_LABELS, l.status),
      l.verdict && l.verdict !== "n/a" ? labelText(VERDICT_LABELS, l.verdict) : "—",
      trunc(l.stderr_excerpt ?? (l.verdict_evidence ?? []).join("; "), 66),
    ]);
    y = table(doc, at, {
      startY: y,
      head: [["Test", "Title", "Technique", "Target", "Status", "Verdict", "Evidence"]],
      body: rows,
      styles: { fontSize: 6.8, cellPadding: 3, overflow: "linebreak", lineColor: BORDER, lineWidth: 0.4 },
      columnStyles: {
        0: { cellWidth: 66, font: "courier" },
        1: { cellWidth: 100 },
        6: { cellWidth: 120 },
      },
      didParseCell: (d) => {
        if (d.section !== "body" || d.column.index !== 5) return;
        const v = String(d.cell.raw ?? "").toLowerCase();
        if (v.includes("vulnerable")) {
          d.cell.styles.textColor = DANGER;
          d.cell.styles.fontStyle = "bold";
        } else if (v.includes("resilient")) {
          d.cell.styles.textColor = SUCCESS;
        } else if (v.includes("inconclusive")) {
          d.cell.styles.textColor = CAUTION;
        }
      },
    });
  }

  // ── Test design techniques ──
  const byTech = a.test_suite_summary?.by_technique;
  if (byTech && Object.keys(byTech).length) {
    y = sectionHeading(doc, y, "Test Design Techniques — ISTQB / ISO 29119-4");
    const rows = Object.entries(byTech).map(([t, v]) => [
      labelText(TECHNIQUE_LABELS, t),
      String((v as { planned?: number }).planned ?? 0),
      String((v as { executed?: number }).executed ?? 0),
    ]);
    y = table(doc, at, {
      startY: y,
      head: [["Technique", "Planned", "Executed"]],
      body: rows,
      columnStyles: { 1: { halign: "center", cellWidth: 80 }, 2: { halign: "center", cellWidth: 80 } },
    });
  }

  // ── Surface map / traceability ──
  const bindings = Object.values((a.surface_map ?? {}) as Record<string, SurfaceBinding>);
  if (bindings.length) {
    y = sectionHeading(doc, y, pre ? "Design Traceability" : "Surface Map & Traceability");
    const rows = bindings.map((b) => [
      b.req_id,
      labelText(SURFACE_STATE_LABELS, b.state),
      b.threat_class ? labelText(THREAT_CLASS_LABELS, b.threat_class) : "—",
      b.defense_kind ? labelText(DEFENSE_KIND_LABELS, b.defense_kind) : "—",
      b.attestation_mode ? labelText(ATTESTATION_MODE_LABELS, b.attestation_mode) : "—",
      trunc((b.backend_endpoints ?? []).map((e) => `${e.method} ${e.path}`).join(", "), 54),
    ]);
    y = table(doc, at, {
      startY: y,
      head: [["Requirement", "Surface", "Threat", "Defense", "Attestation", "Endpoints"]],
      body: rows,
      styles: { fontSize: 7, cellPadding: 3, overflow: "linebreak", lineColor: BORDER, lineWidth: 0.4 },
      columnStyles: { 0: { cellWidth: 66, font: "courier" } },
    });
  }

  // ── Coverage gaps ──
  const gaps = a.coverage_gaps ?? [];
  if (gaps.length) {
    y = sectionHeading(doc, y, "Coverage Gaps — Honest Abstentions");
    y = table(doc, at, {
      startY: y,
      head: [["Requirement", "Acceptance criterion", "Reason"]],
      body: gaps.map((g) => [
        String(g.requirement_id ?? "—"),
        trunc(String(g.acceptance_criterion ?? ""), 56),
        trunc(String(g.reason ?? ""), 80),
      ]),
    });
  }

  // ── Suggested patches (Healer) ──
  const patches = a.suggested_patches ?? [];
  if (patches.length) {
    y = sectionHeading(doc, y, "Suggested Remediations — Healer");
    y = table(doc, at, {
      startY: y,
      head: [["Patch", "Test", "Target file", "OWASP", "Summary"]],
      body: patches.map((p: SuggestedPatch) => [
        p.patch_id,
        p.test_id,
        p.target_file || "(test defect)",
        p.owasp_category ?? "—",
        trunc(p.summary ?? "", 78),
      ]),
      styles: { fontSize: 7, cellPadding: 3, overflow: "linebreak", lineColor: BORDER, lineWidth: 0.4 },
      columnStyles: { 2: { font: "courier", cellWidth: 100 } },
    });
  }

  // ── SAST (Bandit) sidecar ──
  const sast = a.sast_summary as Record<string, unknown> | undefined;
  if (sast && Object.keys(sast).length) {
    y = sectionHeading(doc, y, "Static Analysis — SAST (Bandit)");
    const scalars = Object.entries(sast).filter(([, v]) =>
      ["string", "number", "boolean"].includes(typeof v),
    );
    if (scalars.length) {
      y = table(doc, at, {
        startY: y,
        head: [["Field", "Value"]],
        body: scalars.map(([k, v]) => [humanize(k), String(v)]),
        columnStyles: { 0: { cellWidth: 170 } },
      });
    }
    const arr = Object.values(sast).find((v) => Array.isArray(v)) as unknown[] | undefined;
    if (arr && arr.length && typeof arr[0] === "object" && arr[0] !== null) {
      const keys = Object.keys(arr[0] as object).slice(0, 5);
      y = table(doc, at, {
        startY: y,
        head: [keys.map(humanize)],
        body: (arr.slice(0, 25) as Record<string, unknown>[]).map((o) =>
          keys.map((k) => trunc(String(o[k] ?? ""), 44)),
        ),
        styles: { fontSize: 6.8, cellPadding: 3, overflow: "linebreak", lineColor: BORDER, lineWidth: 0.4 },
      });
    }
  }

  // ── PRE_CODE artifacts ──
  if (pre) {
    const contracts = a.design_contracts ?? [];
    if (contracts.length) {
      y = sectionHeading(doc, y, "Design Contracts");
      y = table(doc, at, {
        startY: y,
        head: [["Requirement", "Method", "Endpoint", "Validation / notes"]],
        body: contracts.map((c) => {
          const cc = c as Record<string, unknown>;
          const raw = String(cc.endpoint ?? cc.path ?? "");
          const m = cc.method
            ? String(cc.method).toUpperCase()
            : (raw.match(/^(GET|POST|PUT|PATCH|DELETE)/i)?.[1]?.toUpperCase() ?? "");
          const rules = Array.isArray(cc.validation_rules)
            ? (cc.validation_rules as unknown[]).map(String).join("; ")
            : String(cc.notes ?? "");
          return [
            String(cc.requirement_id ?? "—"),
            m,
            trunc(raw.replace(/^(GET|POST|PUT|PATCH|DELETE)\s+/i, ""), 40),
            trunc(rules, 80),
          ];
        }),
      });
    }
    const checklist = a.security_checklist ?? [];
    if (checklist.length) {
      y = sectionHeading(doc, y, "Security Checklist");
      y = table(doc, at, {
        startY: y,
        head: [["OWASP", "Requirement", "Instruction"]],
        body: checklist.map((it) => {
          const e = it as Record<string, unknown>;
          return [
            String(e.owasp_id ?? e.owasp_category ?? e.category ?? "—"),
            String(e.requirement_id ?? "—"),
            trunc(String(e.instruction ?? e.requirement ?? e.control ?? ""), 96),
          ];
        }),
      });
    }
  }

  // ── Drift report ──
  const drift = a.drift_report as Record<string, unknown> | undefined;
  if (drift) {
    const summary = (drift.summary ?? drift) as Record<string, unknown>;
    const rows = Object.entries(summary)
      .filter(([, v]) => typeof v === "number")
      .map(([k, v]) => [humanize(k), String(v)]);
    if (rows.length) {
      y = sectionHeading(doc, y, "Drift Report — PRE_CODE vs POST_CODE");
      y = table(doc, at, {
        startY: y,
        head: [["Metric", "Count"]],
        body: rows,
        columnStyles: { 0: { cellWidth: 220 }, 1: { halign: "center" } },
      });
    }
  }

  addChrome(doc, a);
  doc.save(`${fileStem(a, runId)}.pdf`);
}

// ── XLSX ─────────────────────────────────────────────────────────────────────

function summaryRows(a: ProjectState): Record<string, string | number>[] {
  const s = computeSummary(a);
  const cq = a.coverage_quality ?? a.suite_quality;
  const rows: Record<string, string | number>[] = [
    { metric: "Story", value: a.story_title ?? a.story_id ?? "—" },
    { metric: "Pipeline mode", value: String(a.pipeline_mode) },
    { metric: "Run validity", value: `${a.run_validity} — ${labelText(RUN_VALIDITY_LABELS, a.run_validity)}` },
    { metric: "Coverage quality", value: cq ? `${cq} — ${labelText(COVERAGE_QUALITY_LABELS, cq)}` : "—" },
    { metric: "Total tests", value: s.total },
    { metric: "Passed", value: s.passed },
    { metric: "Failed", value: s.failed },
    { metric: "Errored", value: s.error },
    { metric: "Skipped", value: s.skipped },
    { metric: "Success %", value: `${s.successPct}%` },
  ];
  if (s.resiliencePct != null) rows.push({ metric: "Resilience %", value: `${Math.round(s.resiliencePct)}%` });
  if (s.resilient != null) rows.push({ metric: "Resilient", value: s.resilient });
  if (s.vulnerable != null) rows.push({ metric: "Vulnerable", value: s.vulnerable });
  if (s.unclassified != null) rows.push({ metric: "Unclassified", value: s.unclassified });
  return rows;
}

function findingsRows(a: ProjectState): Record<string, string | number>[] {
  return (a.execution_logs ?? []).map((l: VerdictRecord) => ({
    test_id: l.test_id,
    title: l.title ?? "",
    category: l.category ?? "",
    technique: l.technique ?? "",
    exploit_target: l.exploit_target ?? "",
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
    attestation_mode: b.attestation_mode ?? "",
    endpoints: (b.backend_endpoints ?? []).map((e) => `${e.method} ${e.path}`).join(", "),
    confidence: b.confidence ?? "",
  }));
}

/** Real .xlsx workbook — one sheet per report section that has data. */
export async function exportXlsx(a: ProjectState, runId?: string): Promise<void> {
  const XLSX = await import("xlsx");
  const wb = XLSX.utils.book_new();
  const add = (name: string, rows: Record<string, unknown>[]) => {
    if (rows.length) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), name.slice(0, 31));
  };

  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(summaryRows(a)), "Summary");
  add("Findings", findingsRows(a));
  add("Surface Map", surfaceRows(a));

  const posture = a.security_posture;
  if (posture?.by_exploit_target) {
    add(
      "OWASP Posture",
      Object.entries(posture.by_exploit_target).map(([target, v]) => ({
        target,
        attempted: v.attempted ?? 0,
        resilient: v.resilient ?? 0,
        vulnerable: v.vulnerable ?? 0,
        skipped: v.skipped ?? 0,
        errored: v.errored ?? 0,
        unclassified: v.unclassified ?? 0,
      })),
    );
  }

  const byTech = a.test_suite_summary?.by_technique;
  if (byTech) {
    add(
      "Techniques",
      Object.entries(byTech).map(([technique, v]) => ({
        technique,
        planned: (v as { planned?: number }).planned ?? 0,
        executed: (v as { executed?: number }).executed ?? 0,
      })),
    );
  }

  add(
    "Suggested Patches",
    (a.suggested_patches ?? []).map((p) => ({
      patch_id: p.patch_id,
      test_id: p.test_id,
      target_file: p.target_file ?? "",
      owasp: p.owasp_category ?? "",
      summary: p.summary ?? "",
      bug_explanation: p.bug_explanation ?? "",
    })),
  );

  add(
    "Coverage Gaps",
    (a.coverage_gaps ?? []).map((g) => ({
      requirement_id: g.requirement_id ?? "",
      acceptance_criterion: g.acceptance_criterion ?? "",
      reason: g.reason ?? "",
    })),
  );

  const sast = a.sast_summary as Record<string, unknown> | undefined;
  if (sast) {
    const arr = Object.values(sast).find((v) => Array.isArray(v)) as Record<string, unknown>[] | undefined;
    if (arr?.length) add("SAST", arr);
    else {
      add(
        "SAST",
        Object.entries(sast)
          .filter(([, v]) => ["string", "number", "boolean"].includes(typeof v))
          .map(([field, value]) => ({ field, value: String(value) })),
      );
    }
  }

  if (isPre(a)) {
    add("Design Contracts", (a.design_contracts ?? []) as Record<string, unknown>[]);
    add("Security Checklist", (a.security_checklist ?? []) as Record<string, unknown>[]);
  }

  XLSX.writeFile(wb, `${fileStem(a, runId)}.xlsx`);
}
