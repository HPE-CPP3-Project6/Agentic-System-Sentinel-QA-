import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { enableMocking } from "./mocks/browser";
import "./styles/globals.css";

async function bootstrap() {
  await enableMocking();
  const root = document.getElementById("root");
  if (!root) throw new Error("Root element not found");
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();
