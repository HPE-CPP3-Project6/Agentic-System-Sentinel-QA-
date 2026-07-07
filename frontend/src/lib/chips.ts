import { cn } from "@/lib/cn";

/** Theme-aware chip classes — see globals.css `.chip-*` */
export const CHIP = {
  neutral: "chip chip-neutral",
  info: "chip chip-info",
  success: "chip chip-success",
  warn: "chip chip-warn",
  danger: "chip chip-danger",
} as const;

export const STATUS_BANNER = {
  success: "status-banner status-banner-success",
  warn: "status-banner status-banner-warn",
  danger: "status-banner status-banner-danger",
  neutral: "status-banner status-banner-neutral",
} as const;

const HTTP_METHOD_CHIP: Record<string, string> = {
  GET: "chip chip-http-get",
  POST: "chip chip-http-post",
  PUT: "chip chip-http-put",
  PATCH: "chip chip-http-patch",
  DELETE: "chip chip-http-delete",
};

export function httpMethodChip(method?: string | null): string {
  const key = (method ?? "").toUpperCase();
  if (key === "ANY") return CHIP.neutral;
  return HTTP_METHOD_CHIP[key] ?? CHIP.neutral;
}

/** OWASP category chip — danger for injection/access, warn for design/auth, info default */
export function owaspChip(owaspId?: string | null): string {
  const key = (owaspId ?? "").split(":")[0].toUpperCase();
  if (["A01", "A02", "A03", "A08", "A10"].includes(key)) return CHIP.danger;
  if (["A04", "A05", "A06", "A07"].includes(key)) return CHIP.warn;
  return CHIP.info;
}

export function httpStatusCodeClass(code: string): string {
  if (code.startsWith("2")) return "text-success font-mono font-bold";
  if (code.startsWith("4")) return "text-caution font-mono font-bold";
  if (code.startsWith("5")) return "text-danger font-mono font-bold";
  return "text-foreground font-mono font-bold";
}

export function chipClass(
  tone: "default" | "good" | "warn" | "bad" | "new",
  extra?: string,
): string {
  const base =
    tone === "good"
      ? CHIP.success
      : tone === "warn"
        ? CHIP.warn
        : tone === "bad"
          ? CHIP.danger
          : tone === "new"
            ? CHIP.info
            : CHIP.neutral;
  return cn(base, extra);
}
