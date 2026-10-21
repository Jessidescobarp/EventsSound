import { useCallback, useEffect, useState } from "react";
import {
  classifyConfigError,
  fetchAgentConfig,
  previewAgentConfig,
  type AgentConfig,
  type Preview,
} from "../api/adminAgentConfig";
import { AgentConfigForm } from "../components/admin/AgentConfigForm";
import { ModelInUseCard } from "../components/admin/ModelInUseCard";
import { PreviewDetails } from "../components/admin/PreviewDetails";
import { failureText, useConfigCall } from "../components/admin/useConfigCall";
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
  const { busy, failure, run } = useConfigCall((e) => {
    if (e.kind === "version_conflict") reload();
  });
  const [preview, setPreview] = useState<Preview | null>(null);

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
  const review = async (changes: Partial<AgentConfig>) => {
    setPreview(null);
    const result = await run((tk, signal) => previewAgentConfig({ changes, base_version: view.version }, tk, signal));
    if (result) setPreview(result);
  };

  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-ink-muted">{t.lead}</p>
      <Alert tone="warn" title={t.warningTitle} role="note">
        {t.warningBody}
      </Alert>
      <ModelInUseCard model={view.model_in_use} version={view.version} />
      {failure ? <Alert tone="danger" title={failureText(failure)} role="alert" /> : null}
      <AgentConfigForm key={view.version} view={view} busy={busy} onReview={(changes) => void review(changes)} />
      {preview ? (
        <section aria-labelledby="agent-summary" className="space-y-3 rounded-card border border-line p-5">
          <h2 id="agent-summary" className="text-xl font-semibold">
            {t.summaryTitle}
          </h2>
          <PreviewDetails preview={preview} />
        </section>
      ) : null}
    </div>
  );
}
