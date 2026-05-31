import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/cn";

const badgeVariants = cva(
  "inline-flex items-center px-2 py-0.5 text-xs font-semibold uppercase tracking-wide",
  {
    variants: {
      variant: {
        default: "bg-primary/15 text-primary",
        success: "severity-pass",
        caution: "bg-caution-bg text-caution",
        danger: "bg-danger-bg text-danger",
        critical: "severity-critical",
        high: "severity-high",
        medium: "severity-medium",
        low: "severity-low",
        muted: "bg-surface-elevated text-muted border border-border",
        outline: "border border-border text-foreground bg-surface",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
