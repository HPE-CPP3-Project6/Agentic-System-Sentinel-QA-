import { useEffect, type ReactNode } from "react";
import { Toaster } from "sonner";
import { applyTheme, getStoredTheme } from "@/lib/theme";
import { useUiStore } from "@/stores/uiStore";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);

  useEffect(() => {
    const stored = getStoredTheme();
    setTheme(stored);
    applyTheme(stored);
  }, [setTheme]);

  return (
    <>
      {children}
      <Toaster theme={theme} position="bottom-right" />
    </>
  );
}
