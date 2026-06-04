import {
  Activity,
  ArrowLeft,
  Moon,
  Sun,
} from "lucide-react";
import { Link, useLocation } from "wouter";
import { useHealth } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { applyTheme, toggleTheme } from "@/lib/theme";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/stores/uiStore";
import { RunStatusPill } from "@/components/RunStatusPill";

interface TopbarProps {
  title?: string;
  showBack?: boolean;
  activeNav?: "stories" | "workspace" | "reports";
}

export function Topbar({ title, showBack, activeNav = "stories" }: TopbarProps) {
  const { data: health } = useHealth();
  const [, setLocation] = useLocation();
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);

  return (
    <header className="sticky top-0 z-40 bg-nav text-nav-fg">
      <div className="flex h-12 items-center gap-6 px-4">
        <Link href="/" className="flex shrink-0 items-center gap-2 text-nav-fg no-underline">
          <Activity className="h-5 w-5" strokeWidth={1.75} aria-hidden />
          <span className="text-sm font-semibold tracking-tight">Sentinel-QA</span>
        </Link>

        <nav className="hidden items-center md:flex" aria-label="Main">
          <Link
            href="/"
            className={cn("nav-tab no-underline", activeNav === "stories" && "nav-tab-active")}
          >
            Stories
          </Link>
          {showBack && (
            <span
              className={cn(
                "nav-tab",
                activeNav === "workspace" && "nav-tab-active",
              )}
            >
              Pipeline
            </span>
          )}
        </nav>

        {title && (
          <span className="hidden truncate text-sm text-nav-muted lg:inline">
            {title}
          </span>
        )}

        <div className="ml-auto flex items-center gap-1">
          <RunStatusPill />
          {health && (
            <div className="mr-2 hidden items-center gap-2 lg:flex">
              <HealthBadge ok={health.chroma_ok} label="Index" />
              <HealthBadge ok={health.target_app_ok} label="Target" />
            </div>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="text-nav-fg hover:bg-white/10 hover:text-nav-fg"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            onClick={() => {
              const next = toggleTheme(theme);
              setTheme(next);
              applyTheme(next);
            }}
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4" strokeWidth={1.75} />
            ) : (
              <Moon className="h-4 w-4" strokeWidth={1.75} />
            )}
          </Button>
          {showBack && (
            <Button
              variant="ghost"
              size="sm"
              className="ml-1 text-nav-fg hover:bg-white/10 hover:text-nav-fg"
              onClick={() => setLocation("/")}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={1.75} />
              Stories
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}

function HealthBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <Badge variant={ok ? "success" : "danger"} className="normal-case">
      {label}: {ok ? "OK" : "DOWN"}
    </Badge>
  );
}
