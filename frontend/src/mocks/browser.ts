import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

export async function enableMocking() {
  if (import.meta.env.VITE_USE_MSW !== "true") return;
  try {
    const worker = setupWorker(...handlers);
    await worker.start({ onUnhandledRequest: "bypass" });
  } catch (err) {
    console.warn("[MSW] Mock API unavailable — connect a real backend or re-run `npx msw init public/`", err);
  }
}
