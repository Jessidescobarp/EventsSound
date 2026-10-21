import { useCallback, useEffect } from "react";
import { classifyConfigError, fetchAgentConfig } from "../api/adminAgentConfig";
import { ModelInUseCard } from "../components/admin/ModelInUseCard";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Spinner } from "../components/ui/Spinner";
import { useAuth } from "../auth/authContext";
import { es } from "../copy/es";
import { useRequest } from "../hooks/useRequest";

const t = es.agentAdmin;

/** Admin tab "Agente": the model in use and the editable configuration. */
export function AdminAgentPage() {
  const { session, expireSession } = useAuth();
  const token = session?.token ?? "";
  const load = useCallback((signal: AbortSignal) => fetchAgentConfig(token, signal), [token]);
  const { state, reload } = useRequest(load);

  const unauthenticated = state.status === "error" && classifyConfigError(state.error) === "unauthenticated";
  useEffect(() => {
    if (unauthenticated) expireSession();
  }, [unauthenticated, expireSession]);

  if (state.status === "loading") {
    return (
      <div role="status" className="flex items-center gap-3 text-ink-muted">
        <Spinner />
        <span>{es.records.loading}</span>
      </div>
    );
  }
  if (state.status === "error") {
    return unauthenticated ? (
      <Alert tone="info" title={t.sessionEnded} role="status" />
    ) : (
      <div className="max-w-xl space-y-4">
        <Alert tone="warn" title={t.loadError} role="alert">
          {es.records.errorBody}
        </Alert>
        <Button variant="secondary" onClick={reload}>
          {es.common.retry}
        </Button>
      </div>
    );
  }

  const view = state.data;
  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-ink-muted">{t.lead}</p>
      <Alert tone="warn" title={t.warningTitle} role="note">
        {t.warningBody}
      </Alert>
      <ModelInUseCard model={view.model_in_use} version={view.version} />
    </div>
  );
}
