import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import { isMockMode } from "./env";
import "./styles/index.css";

async function bootstrap() {
  // Demo data is opt-in: the flag (isMockMode) AND a non-production mode. MODE is a literal
  // in builds, so a production bundle folds this to false and drops the dynamic import
  // (and src/mocks); build/check-no-mocks.mjs verifies that in CI.
  if (import.meta.env.MODE !== "production" && isMockMode()) {
    const { installMocks } = await import("./mocks/fakeApi");
    installMocks();
  }

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </StrictMode>,
  );
}

void bootstrap();
