import { useEffect, useState } from "react";
import { createHighlighter, type Highlighter } from "shiki";
import { useUiStore } from "@/stores/uiStore";
import { cn } from "@/lib/cn";

interface CodePanelProps {
  code: string;
  lang?: string;
  /** Extra classes (e.g. a tighter `max-h-*`) merged over the defaults. */
  className?: string;
}

let highlighterPromise: Promise<Highlighter> | null = null;

function getHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      themes: ["github-light", "github-dark"],
      langs: ["python"],
    });
  }
  return highlighterPromise;
}

function panelSurfaceClasses(isDark: boolean) {
  return isDark
    ? "bg-console-bg text-console-fg"
    : "bg-code-panel-bg text-foreground";
}

export function CodePanel({ code, lang = "python", className }: CodePanelProps) {
  const theme = useUiStore((s) => s.theme);
  const isDark = theme === "dark";
  const [html, setHtml] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    void (async () => {
      const hl = await getHighlighter();
      const shikiTheme = isDark ? "github-dark" : "github-light";
      const themed = hl.codeToHtml(code, {
        lang,
        theme: shikiTheme,
      });
      if (!cancelled) {
        setHtml(themed);
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code, lang, isDark]);

  const surface = panelSurfaceClasses(isDark);

  if (loading) {
    return (
      <pre
        className={cn(
          "min-w-0 max-w-full overflow-x-auto border border-border p-4 font-mono text-xs",
          surface,
          className,
        )}
      >
        {code}
      </pre>
    );
  }

  return (
    <div
      className={cn(
        "code-panel max-h-[65vh] w-full min-w-0 max-w-full overflow-x-auto overflow-y-auto border border-border text-xs [&_pre]:!bg-transparent [&_pre]:p-4 [&_pre]:font-mono",
        surface,
        className,
      )}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
