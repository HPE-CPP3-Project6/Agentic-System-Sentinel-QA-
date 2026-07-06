import { ShieldCheck, ShieldAlert, FileCode2, PlugZap } from "lucide-react";
import type { ProjectState } from "@/api/types";
import {
  COVERAGE_QUALITY_LABELS,
  FIELD_LABELS,
  RUN_VALIDITY_LABELS,
  lookupLabel,
} from "@/lib/labels";
import { InfoTip } from "@/components/EnumLabel";
import { cn } from "@/lib/cn";

/**
 * The two-axis attestation, surfaced as the hero of the report:
 *   run_validity     — did we actually exercise the app? (read FIRST)
 *   coverage_quality — was the suite meaningful? (only trusted if run is OK)
 * Colour-coded so a reviewer reads trustworthiness at a glance. Labels + blurbs
 * come from the shared label module (@/lib/labels); only the icon/accent styling
 * lives here.
 */
const VALIDITY_STYLE: Record<
  string,
  { tone: string; accent: string; Icon: typeof ShieldCheck }
> = {
  OK: { tone: "text-success", accent: "border-l-success bg-success/5", Icon: ShieldCheck },
  FUNCTIONALLY_UNRELIABLE: {
    tone: "text-caution",
    accent: "border-l-caution bg-caution-bg/40",
    Icon: ShieldAlert,
  },
  TARGET_UNREACHABLE: {
    tone: "text-danger",
    accent: "border-l-danger bg-danger-bg/40",
    Icon: PlugZap,
  },
  DESIGN_ONLY: {
    tone: "text-primary",
    accent: "border-l-primary bg-primary/5",
    Icon: FileCode2,
  },
  NOT_ATTESTED: {
    tone: "text-caution",
    accent: "border-l-caution bg-caution-bg/40",
    Icon: ShieldAlert,
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
  const style = VALIDITY_STYLE[artifact.run_validity] ?? VALIDITY_STYLE.OK;
  const validity = lookupLabel(RUN_VALIDITY_LABELS, artifact.run_validity);
  const ev = (artifact.metadata?.run_validity_evidence ?? {}) as Record<string, unknown>;
  const evidenceLine =
    typeof ev.reason === "string"
      ? ev.reason
      : artifact.attestation_banner ?? validity.blurb;
  const metric = metricFor(artifact);
  const coverage = artifact.coverage_quality ?? artifact.suite_quality;
  const coverageMeta = lookupLabel(COVERAGE_QUALITY_LABELS, coverage);
  const { Icon } = style;

  return (
    <div className={cn("panel flex flex-wrap items-center gap-5 border-l-4 p-4", style.accent)}>
      <div className="flex items-center gap-3">
        <Icon className={cn("h-7 w-7", style.tone)} strokeWidth={1.6} />
        <div>
          <InfoTip
            blurb={FIELD_LABELS.run_validity.blurb}
            className={cn("text-[11px] font-semibold uppercase tracking-wider", style.tone)}
          >
            {FIELD_LABELS.run_validity.label}
          </InfoTip>
          <p className="text-lg font-semibold leading-tight">{validity.label}</p>
        </div>
      </div>

      <div className="h-10 w-px bg-border" />

      <div>
        <InfoTip
          blurb={FIELD_LABELS.coverage_quality.blurb}
          className="text-[11px] font-semibold uppercase tracking-wider text-muted"
        >
          {FIELD_LABELS.coverage_quality.label}
        </InfoTip>
        <p className="text-lg font-semibold leading-tight">
          {coverage ? coverageMeta.label : "—"}
        </p>
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
