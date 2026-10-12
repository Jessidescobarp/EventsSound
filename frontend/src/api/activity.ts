/**
 * Tiny event bus: apiFetch announces every valid response, so the backend status
 * (warm-up banner) learns that the server is up from ANY call, not only /health.
 */
type Listener = () => void;

const listeners = new Set<Listener>();

export function onApiSuccess(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function notifyApiSuccess(): void {
  for (const listener of [...listeners]) listener();
}
