import { Badge } from "@/components/ui/badge";
import type { SuiteQuality } from "@/api/types";

const CONFIG: Record<
  SuiteQuality,
  { label: string; sub: string; variant: "success" | "caution" | "danger" | "muted" | "critical" | "high" }
> = {
  ATTESTABLE: { label: "Trusted", sub: "Meaningful coverage.", variant: "success" },
  INSUFFICIENT: { label: "Caution", sub: "Coverage below floor.", variant: "caution" },
  PROXY_HEAVY: { label: "Degraded", sub: "High off-target rate.", variant: "high" },
  // Stage-1 honest verdict: > 30% of adversarial tests had no Resolver/
  // Generator stamp. The resilience % was computed against the rest of
  // the suite only — don't read it as a clean attestation.
  INCONCLUSIVE_HEAVY: {
    label: "Unclassified",
    sub: "Many adversarial tests had no attestation stamp; resilience % is partial.",
    variant: "caution",
  },
  NO_RISKS_PREDICTED: { label: "Review", sub: "No OWASP exposure predicted.", variant: "muted" },
  ALL_SKIPPED: { label: "Inconclusive", sub: "All tests skipped.", variant: "muted" },
  NO_TESTS_GENERATED: { label: "Blocked", sub: "No tests generated.", variant: "critical" },
  NO_REQUIREMENTS: { label: "No requirements", sub: "Critic produced no requirements.", variant: "muted" },
  DESIGN_COMPLETE: { label: "Design ready", sub: "Contracts + checklist present.", variant: "success" },
  DESIGN_INSUFFICIENT: { label: "Design gap", sub: "Missing design artifacts.", variant: "caution" },
};

export function SuiteQualityBadge({ quality }: { quality?: SuiteQuality }) {
  if (!quality) return <Badge variant="muted">Unknown</Badge>;
  const cfg = CONFIG[quality];
  return (
    <div>
      <Badge variant={cfg.variant} className="normal-case">{cfg.label}</Badge>
      <p className="mt-1 text-xs text-muted">{cfg.sub}</p>
    </div>
  );
}
