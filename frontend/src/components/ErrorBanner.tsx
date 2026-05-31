import { AlertTriangle, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface ErrorBannerProps {
  code: string;
  message: string;
  detail?: string;
  onDismiss?: () => void;
  className?: string;
}

export function ErrorBanner({
  code,
  message,
  detail,
  onDismiss,
  className,
}: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 border border-danger bg-danger-bg px-4 py-3 text-sm text-danger",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} />
      <div className="flex-1">
        <p className="font-semibold uppercase tracking-wide">{code.replace(/_/g, " ")}</p>
        <p className="mt-0.5">{message}</p>
        {detail && <p className="mt-1 text-xs opacity-80">{detail}</p>}
      </div>
      {onDismiss && (
        <Button variant="ghost" size="icon" onClick={onDismiss} aria-label="Dismiss">
          <X className="h-4 w-4" strokeWidth={1.75} />
        </Button>
      )}
    </div>
  );
}
