import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import "./styles/index.css";

async function bootstrap() {
  // Demo data is opt-in at dev/build time. Written inline (not via a helper) so bundlers
  // drop the dynamic import, and with it src/mocks, when the flag is not "true".
  if (import.meta.env.VITE_USE_MOCKS === "true") {
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
