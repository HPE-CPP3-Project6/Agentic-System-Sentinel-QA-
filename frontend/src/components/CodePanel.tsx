import { useEffect, useState } from "react";
import { createHighlighter, type Highlighter } from "shiki";

interface CodePanelProps {
  code: string;
  lang?: string;
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

export function CodePanel({ code, lang = "python" }: CodePanelProps) {
  const [html, setHtml] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    void (async () => {
      const hl = await getHighlighter();
      const isDark = document.documentElement.classList.contains("dark");
      const themed = hl.codeToHtml(code, {
        lang,
        theme: isDark ? "github-dark" : "github-light",
      });
      if (!cancelled) {
        setHtml(themed);
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code, lang]);

  if (loading) {
    return (
      <pre className="min-w-0 max-w-full overflow-x-auto bg-console-bg p-4 font-mono text-xs text-console-fg">
        {code}
      </pre>
    );
  }

  return (
    <div
      className="code-panel max-h-[65vh] w-full min-w-0 max-w-full overflow-x-auto overflow-y-auto border border-border bg-console-bg text-xs [&_pre]:!bg-transparent [&_pre]:p-4 [&_pre]:font-mono"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
