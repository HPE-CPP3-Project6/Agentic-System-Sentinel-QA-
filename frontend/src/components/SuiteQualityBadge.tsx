import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { SuiteQuality } from "@/api/types";
import { COVERAGE_QUALITY_LABELS, lookupLabel } from "@/lib/labels";

// Colour only — label + blurb come from the shared label module so there is one
// home for the coverage-quality vocabulary.
const VARIANT: Record<SuiteQuality, BadgeProps["variant"]> = {
  ATTESTABLE: "success",
  INSUFFICIENT: "caution",
  PROXY_HEAVY: "high",
  INCONCLUSIVE_HEAVY: "caution",
  NO_RISKS_PREDICTED: "muted",
  ALL_SKIPPED: "muted",
  NO_TESTS_GENERATED: "critical",
  NO_REQUIREMENTS: "muted",
  DESIGN_COMPLETE: "success",
  DESIGN_INSUFFICIENT: "caution",
};

export function SuiteQualityBadge({ quality }: { quality?: SuiteQuality }) {
  if (!quality) return <Badge variant="muted">Unknown</Badge>;
  const meta = lookupLabel(COVERAGE_QUALITY_LABELS, quality);
  return (
    <div>
      <Badge variant={VARIANT[quality] ?? "muted"} className="normal-case">
        {meta.label}
      </Badge>
      <p className="mt-1 text-xs text-muted">{meta.blurb}</p>
    </div>
  );
}
