import { create } from "zustand";
import type { Theme } from "@/lib/theme";
import { getStoredTheme } from "@/lib/theme";

type WsConnectionStatus = "idle" | "connecting" | "connected" | "disconnected" | "error";

interface UiState {
  theme: Theme;
  activeRunId: string | null;
  wsStatus: WsConnectionStatus;
  setTheme: (theme: Theme) => void;
  setActiveRunId: (runId: string | null) => void;
  setWsStatus: (status: WsConnectionStatus) => void;
}

export const useUiStore = create<UiState>((set) => ({
  theme: getStoredTheme(),
  activeRunId: null,
  wsStatus: "idle",
  setTheme: (theme) => set({ theme }),
  setActiveRunId: (activeRunId) => set({ activeRunId }),
  setWsStatus: (wsStatus) => set({ wsStatus }),
}));
