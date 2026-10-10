import { useEffect, useState } from "react";
import { checkHealth } from "./api/health";
import { getApiBaseUrl } from "./env";
import "./App.css";

type Status = "loading" | "ok" | "error";

// Render free instances can take about a minute to wake up.
const RETRY_WINDOW_MS = 90_000;
const RETRY_INTERVAL_MS = 5_000;

const MESSAGES: Record<Status, string> = {
  loading: "Cargando estado del servicio...",
  ok: "Servicio operativo",
  error: "Servicio no disponible",
};

export default function App() {
  const [status, setStatus] = useState<Status>("loading");

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = Date.now() + RETRY_WINDOW_MS;

    const attempt = async () => {
      try {
        getApiBaseUrl();
      } catch (error) {
        console.error(error);
        setStatus("error");
        return;
      }
      try {
        await checkHealth();
        if (!cancelled) setStatus("ok");
      } catch {
        if (cancelled) return;
        if (Date.now() + RETRY_INTERVAL_MS >= deadline) {
          setStatus("error");
        } else {
          timer = setTimeout(attempt, RETRY_INTERVAL_MS);
        }
      }
    };

    void attempt();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return (
    <>
      <header>
        <h1>EventsSound</h1>
      </header>
      <main>
        <p role="status" className={`status status-${status}`}>
          {MESSAGES[status]}
        </p>
      </main>
    </>
  );
}
