import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import App from "../App";
import { createFakeFetch } from "../mocks/fakeApi";

/**
 * Renders the whole app at `path`. Fetch is the fake API with no latency unless the
 * test already stubbed it; the API base URL is stubbed so health checks run.
 */
export function renderApp(path = "/", fetchImpl: typeof fetch = createFakeFetch({ latencyMs: 0 })) {
  vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
  vi.stubGlobal("fetch", vi.fn(fetchImpl));
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}
