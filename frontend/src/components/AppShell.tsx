import type { ReactNode } from "react";
import { Topbar } from "./Topbar";

interface AppShellProps {
  children: ReactNode;
  title?: string;
  showBack?: boolean;
  activeNav?: "stories" | "workspace" | "reports";
  subHeader?: ReactNode;
}

export function AppShell({
  children,
  title,
  showBack,
  activeNav,
  subHeader,
}: AppShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Topbar title={title} showBack={showBack} activeNav={activeNav} />
      {subHeader}
      <main className="flex-1">{children}</main>
    </div>
  );
}
