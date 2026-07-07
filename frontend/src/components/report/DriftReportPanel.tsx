import { ArrowRight, CheckCircle2, GitCompareArrows, AlertTriangle, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { chipClass, STATUS_BANNER } from "@/lib/chips";
import { DRIFT_HEADLINE_LABELS, DRIFT_METRIC_LABELS, lookupLabel, owaspLabel } from "@/lib/labels";
import { cn } from "@/lib/cn";

export type DriftChecklistItem = {
  owasp_id?: string;
  requirement_id?: string;
  instruction?: string;
  definition_of_done?: string;
  verdict?: string;
};

export type DriftReport = {
  story_id?: string;
  error?: string;
  skipped?: string;
  seeded_snapshot_path?: string;
  headline?: { status?: string; message?: string };
  summary?: Record<string, number>;
  predicted_risks_full?: string[];
  phase2_risks_full?: string[];
  confirmed_risks?: string[];
  missed_risks?: string[];
  new_risks_phase2_only?: string[];
  confirmed_and_exploited?: string[];
  confirmed_checklist_items?: DriftChecklistItem[];
  ignored_checklist_items?: DriftChecklistItem[];
};

const HEADLINE_ICON: Record<string, typeof CheckCircle2> = {
  aligned: CheckCircle2,
  partial: AlertTriangle,
  exploited: XCircle,
  no_prediction: AlertTriangle,
};

const HEADLINE_BANNER: Record<string, string> = {
  aligned: STATUS_BANNER.success,
  partial: STATUS_BANNER.warn,
  exploited: STATUS_BANNER.danger,
  no_prediction: STATUS_BANNER.neutral,
};

function RiskChip({ id, tone = "default" }: { id: string; tone?: "default" | "good" | "warn" | "bad" | "new" }) {
  const meta = owaspLabel(id);

  return (
    <span className={chipClass(tone)} title={meta.blurb}>
      <span className="font-mono font-bold">{id}</span>
      <span className="text-[11px] font-medium opacity-90">{meta.label}</span>
    </span>
  );
}

function MetricTile({ keyName, value }: { keyName: string; value: number }) {
  const meta = lookupLabel(DRIFT_METRIC_LABELS, keyName);
  return (
    <div className="rounded-lg border border-border bg-surface-elevated/50 p-3" title={meta.blurb || undefined}>
      <p className="section-label">{meta.label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">{value}</p>
    </div>
  );
}

function ChecklistBlock({
  title,
  items,
  variant,
}: {
  title: string;
  items: DriftChecklistItem[];
  variant: "good" | "bad";
}) {
  if (!items.length) return null;

  return (
    <div>
      <p className="section-label mb-2">{title}</p>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div
            key={i}
            className={cn(
              "rounded-lg border p-3 text-xs",
              variant === "bad" ? "border-danger/30 bg-danger-bg/50" : "border-success/30 bg-success-bg/50",
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              {item.owasp_id ? (
                <RiskChip id={item.owasp_id.split(":")[0]} tone={variant === "bad" ? "bad" : "good"} />
              ) : null}
              {item.requirement_id ? (
                <Badge variant="outline" className="font-mono text-[10px]">
                  {item.requirement_id}
                </Badge>
              ) : null}
            </div>
            {item.instruction ? <p className="mt-2 text-secondary">{item.instruction}</p> : null}
            {item.definition_of_done ? (
              <p className="mt-1 text-muted">
                <span className="font-medium text-secondary">Done when: </span>
                {item.definition_of_done}
              </p>
            ) : null}
            {item.verdict ? <p className="mt-2 text-[11px] italic text-muted">{item.verdict}</p> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function RiskSection({
  title,
  blurb,
  risks,
  tone,
}: {
  title: string;
  blurb: string;
  risks: string[];
  tone: "good" | "warn" | "bad" | "new";
}) {
  if (!risks.length) return null;
  return (
    <div>
      <p className="text-sm font-medium text-foreground">{title}</p>
      <p className="mb-2 text-xs text-muted">{blurb}</p>
      <div className="flex flex-wrap gap-2">
        {risks.map((r) => (
          <RiskChip key={r} id={r} tone={tone} />
        ))}
      </div>
    </div>
  );
}

function inferHeadline(drift: DriftReport): { status: string; message: string } {
  if (drift.headline?.message) {
    return {
      status: drift.headline.status ?? "aligned",
      message: drift.headline.message,
    };
  }
  const s = drift.summary ?? {};
  const predicted = s.predicted ?? 0;
  const confirmed = s.confirmed_in_phase2 ?? 0;
  const missed = s.missed_in_phase2 ?? 0;
  const exploited = s.exploited ?? 0;
  const ignored = s.checklist_items_ignored ?? 0;

  if (exploited > 0 || ignored > 0) {
    return {
      status: "exploited",
      message: `POST_CODE found ${exploited} exploited predicted risk(s) and ${ignored} ignored checklist item(s).`,
    };
  }
  if (predicted > 0 && missed === 0 && confirmed === predicted) {
    return {
      status: "aligned",
      message: `All ${predicted} PRE_CODE risk prediction(s) confirmed in POST_CODE with no exploited vulnerabilities.`,
    };
  }
  if (predicted === 0) {
    return { status: "no_prediction", message: "PRE_CODE did not predict any OWASP risks for this story." };
  }
  return {
    status: "partial",
    message: `${confirmed} of ${predicted} predicted risk(s) confirmed; ${missed} not seen in POST_CODE.`,
  };
}

export function DriftReportPanel({ drift }: { drift: DriftReport | null | undefined }) {
  if (!drift) return null;

  if (drift.error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitCompareArrows className="h-4 w-4 text-primary" strokeWidth={1.75} />
            Drift report
            <span className="text-xs font-normal text-muted">PRE_CODE → POST_CODE</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted">{drift.error}</CardContent>
      </Card>
    );
  }

  if (drift.skipped) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitCompareArrows className="h-4 w-4 text-primary" strokeWidth={1.75} />
            Drift report
            <span className="text-xs font-normal text-muted">PRE_CODE → POST_CODE</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted">
          <p>{drift.skipped}</p>
          <p className="text-xs">Run PRE_CODE first, then POST_CODE on the same story to compare shift-left predictions against execution.</p>
        </CardContent>
      </Card>
    );
  }

  const summary = drift.summary ?? {};
  const { status: headlineStatus, message: headlineMessage } = inferHeadline(drift);
  const HeadlineIcon = HEADLINE_ICON[headlineStatus] ?? GitCompareArrows;
  const headlineMeta = lookupLabel(DRIFT_HEADLINE_LABELS, headlineStatus);

  const predictedFull =
    drift.predicted_risks_full ??
    (drift.confirmed_risks ?? []).map((r) => (r.includes(":") ? r : `${r}:2021`));
  const phase2Full =
    drift.phase2_risks_full ??
    [
      ...(drift.confirmed_risks ?? []),
      ...(drift.new_risks_phase2_only ?? []),
    ].map((r) => (r.includes(":") ? r : `${r}:2021`));

  const metricKeys = [
    "predicted",
    "confirmed_in_phase2",
    "missed_in_phase2",
    "new_in_phase2_only",
    "exploited",
    "checklist_addressed",
    "checklist_items_ignored",
  ] as const;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitCompareArrows className="h-4 w-4 text-primary" strokeWidth={1.75} />
          Drift report
          <span className="text-xs font-normal text-muted">PRE_CODE design vs POST_CODE execution</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className={HEADLINE_BANNER[headlineStatus] ?? STATUS_BANNER.neutral}>
          <div className="flex items-start gap-3">
            <HeadlineIcon className="mt-0.5 h-5 w-5 shrink-0" strokeWidth={1.75} />
            <div>
              <p className="font-semibold">{headlineMeta.label}</p>
              <p className="mt-1 text-sm">{headlineMessage || headlineMeta.blurb}</p>
            </div>
          </div>
        </div>

        {(predictedFull.length > 0 || phase2Full.length > 0) && (
          <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr] md:items-center">
            <div className="rounded-lg border border-border p-3">
              <p className="section-label">PRE_CODE predicted</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {predictedFull.length
                  ? predictedFull.map((r) => <RiskChip key={r} id={r.split(":")[0]} />)
                  : <span className="text-xs text-muted">None</span>}
              </div>
            </div>
            <ArrowRight className="mx-auto hidden h-5 w-5 text-muted md:block" strokeWidth={1.75} />
            <div className="rounded-lg border border-border p-3">
              <p className="section-label">POST_CODE found</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {phase2Full.length
                  ? phase2Full.map((r) => <RiskChip key={r} id={r.split(":")[0]} tone="new" />)
                  : <span className="text-xs text-muted">None</span>}
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {metricKeys.map((k) =>
            typeof summary[k] === "number" ? <MetricTile key={k} keyName={k} value={summary[k]!} /> : null,
          )}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <RiskSection
            title="Confirmed in POST_CODE"
            blurb="PRE_CODE predicted these risks and POST_CODE tests surfaced them."
            risks={drift.confirmed_risks ?? []}
            tone="good"
          />
          <RiskSection
            title="Predicted but not seen"
            blurb="PRE_CODE flagged these, but POST_CODE did not surface them — may mean controls held or coverage gap."
            risks={drift.missed_risks ?? []}
            tone="warn"
          />
          <RiskSection
            title="New in POST_CODE only"
            blurb="Found during execution but not in the PRE_CODE risk list."
            risks={drift.new_risks_phase2_only ?? []}
            tone="new"
          />
          <RiskSection
            title="Predicted and exploited"
            blurb="Shift-left predicted the risk and adversarial tests confirmed a vulnerability."
            risks={drift.confirmed_and_exploited ?? []}
            tone="bad"
          />
        </div>

        <ChecklistBlock
          title="Shift-left checklist — addressed"
          items={drift.confirmed_checklist_items ?? []}
          variant="good"
        />
        <ChecklistBlock
          title="Shift-left checklist — ignored (vulnerability confirmed)"
          items={drift.ignored_checklist_items ?? []}
          variant="bad"
        />
      </CardContent>
    </Card>
  );
}
