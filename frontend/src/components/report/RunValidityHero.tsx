import { ShieldCheck, ShieldAlert, FileCode2, PlugZap } from "lucide-react";
import type { ProjectState } from "@/api/types";
import { cn } from "@/lib/cn";

/**
 * The two-axis attestation, surfaced as the hero of the report:
 *   run_validity     — did we actually exercise the app? (read FIRST)
 *   coverage_quality — was the suite meaningful? (only trusted if run is OK)
 * Color-coded so a reviewer reads trustworthiness at a glance — the headline
 * differentiator of the pipeline.
 */
const VALIDITY_META: Record<
  string,
  { label: string; tone: string; accent: string; Icon: typeof ShieldCheck; blurb: string }
> = {
  OK: {
    label: "Attestable run",
    tone: "text-success",
    accent: "border-l-success bg-success/5",
    Icon: ShieldCheck,
    blurb: "App was exercised; posture is trustworthy.",
  },
  FUNCTIONALLY_UNRELIABLE: {
    label: "Functionally unreliable",
    tone: "text-caution",
    accent: "border-l-caution bg-caution-bg/40",
    Icon: ShieldAlert,
    blurb: "Most functional failures are test defects — posture suppressed.",
  },
  TARGET_UNREACHABLE: {
    label: "Target unreachable",
    tone: "text-danger",
    accent: "border-l-danger bg-danger-bg/40",
    Icon: PlugZap,
    blurb: "The app was down; nothing was actually attested.",
  },
  DESIGN_ONLY: {
    label: "Design artifact (PRE_CODE)",
    tone: "text-primary",
    accent: "border-l-primary bg-primary/5",
    Icon: FileCode2,
    blurb: "Contracts + checklist generated before code exists; nothing executed.",
  },
};

function metricFor(artifact: ProjectState): { label: string; value: string } | null {
  if (artifact.run_validity === "DESIGN_ONLY") {
    const ds = artifact.design_summary;
    if (ds?.requirements_total != null) {
      return {
        label: "Requirements with contract",
        value: `${ds.requirements_with_contract ?? 0}/${ds.requirements_total}`,
      };
    }
    return null;
  }
  const pct = artifact.security_posture?.resilience_pct ?? artifact.resilience_pct;
  if (pct == null) return null;
  return { label: "Resilience", value: `${Math.round(pct)}%` };
}

export function RunValidityHero({ artifact }: { artifact: ProjectState }) {
  const meta = VALIDITY_META[artifact.run_validity] ?? VALIDITY_META.OK;
  const ev = (artifact.metadata?.run_validity_evidence ?? {}) as Record<string, unknown>;
  const evidenceLine =
    typeof ev.reason === "string"
      ? ev.reason
      : artifact.attestation_banner ?? meta.blurb;
  const metric = metricFor(artifact);
  const coverage = artifact.coverage_quality ?? artifact.suite_quality;
  const { Icon } = meta;

  return (
    <div className={cn("panel flex flex-wrap items-center gap-5 border-l-4 p-4", meta.accent)}>
      <div className="flex items-center gap-3">
        <Icon className={cn("h-7 w-7", meta.tone)} strokeWidth={1.6} />
        <div>
          <p className={cn("text-[11px] font-semibold uppercase tracking-wider", meta.tone)}>
            run_validity
          </p>
          <p className="text-lg font-semibold leading-tight">{meta.label}</p>
        </div>
      </div>

      <div className="h-10 w-px bg-border" />

      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
          coverage_quality
        </p>
        <p className="text-lg font-semibold leading-tight">{coverage ?? "—"}</p>
      </div>

      {metric && (
        <>
          <div className="h-10 w-px bg-border" />
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
              {metric.label}
            </p>
            <p className="text-lg font-semibold leading-tight">{metric.value}</p>
          </div>
        </>
      )}

      <p className="ml-auto max-w-sm text-right text-xs text-muted">{evidenceLine}</p>
    </div>
  );
}
