import type { ReactNode } from "react";
import { lookupLabel, type LabelMeta } from "@/lib/labels";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";

/**
 * Wrap inline content with an on-hover explanation. When `blurb` is empty the
 * children render unchanged (no dotted underline, no tooltip) so unmapped
 * values stay clean.
 */
export function InfoTip({
  blurb,
  className,
  children,
}: {
  blurb?: string;
  className?: string;
  children: ReactNode;
}) {
  if (!blurb) return <span className={className}>{children}</span>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "cursor-help underline decoration-dotted decoration-muted/60 underline-offset-2",
            className,
          )}
        >
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent>{blurb}</TooltipContent>
    </Tooltip>
  );
}

/**
 * A `Badge` whose text is the humanized label for `value`, wrapped in a tooltip
 * carrying the enum's blurb. Colour still comes from the caller's `variant`
 * (the existing per-enum colour maps are unchanged).
 */
export function EnumBadge({
  map,
  value,
  variant,
  className,
}: {
  map: Record<string, LabelMeta>;
  value?: string | null;
  variant?: BadgeProps["variant"];
  className?: string;
}) {
  const meta = lookupLabel(map, value);
  const badge = (
    <Badge variant={variant} className={cn("normal-case", className)}>
      {meta.label}
    </Badge>
  );
  if (!meta.blurb) return badge;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent>{meta.blurb}</TooltipContent>
    </Tooltip>
  );
}
