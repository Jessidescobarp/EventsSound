import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  classifyConfigError,
  fetchAgentConfig,
  previewAgentConfig,
  type ConfigChange,
  type Preview,
} from "../api/adminAgentConfig";
import { AgentConfigForm } from "../components/admin/AgentConfigForm";
import { ConfirmFlow } from "../components/admin/ConfirmFlow";
import { HistoryList } from "../components/admin/HistoryList";
import { ModelInUseCard } from "../components/admin/ModelInUseCard";
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
  const [flow, setFlow] = useState<{ change: ConfigChange; preview: Preview; trigger: HTMLElement | null } | null>(null);
  const [notice, setNotice] = useState<{ tone: "info" | "warn"; text: string } | null>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const loaded = state.status === "success";
  // The reload after an apply replaces the page, so the trigger is gone: focus lands on the notice.
  useEffect(() => {
    if (notice && loaded) noticeRef.current?.focus();
  }, [notice, loaded]);

  const unauthenticated = state.status === "error" && classifyConfigError(state.error) === "unauthenticated";
  useEffect(() => {
    if (unauthenticated) expireSession();
  }, [unauthenticated, expireSession]);

  const finish = (next: { tone: "info" | "warn"; text: string }) => {
    setFlow(null);
    setNotice(next);
    reload();
  };
  // Rendered in every state, in the same slot: a reload while the dialog is open must not remount it.
  const dialogs = flow ? (
    <ConfirmFlow
      change={flow.change}
      initial={flow.preview}
      returnFocus={flow.trigger}
      onClose={() => setFlow(null)}
      onApplied={(version) => finish({ tone: "info", text: t.confirm.applied(version) })}
      onConflict={() => finish({ tone: "warn", text: t.confirm.conflict })}
      onUnknown={reload}
    />
  ) : null;

  let body: ReactNode;
  if (state.status === "loading") {
    body = (
      <div role="status" className="flex items-center gap-3 text-ink-muted">
        <Spinner />
        <span>{es.records.loading}</span>
      </div>
    );
  } else if (state.status === "error") {
    body = unauthenticated ? (
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
  } else {
    const view = state.data;
    const start = async (change: ConfigChange) => {
      const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setNotice(null);
      const preview = await run((tk, signal) => previewAgentConfig(change, tk, signal));
      if (preview) setFlow({ change, preview, trigger });
    };
    body = (
      <div className="space-y-6">
        <p className="max-w-3xl text-ink-muted">{t.lead}</p>
        <Alert tone="warn" title={t.warningTitle} role="note">
          {t.warningBody}
        </Alert>
        {notice ? (
          <div ref={noticeRef} tabIndex={-1}>
            <Alert tone={notice.tone} title={notice.text} role="status" />
          </div>
        ) : null}
        <ModelInUseCard model={view.model_in_use} version={view.version} />
        {failure ? <Alert tone="danger" title={failureText(failure)} role="alert" /> : null}
        <AgentConfigForm
          key={view.version}
          view={view}
          busy={busy}
          onReview={(changes) => void start({ changes, base_version: view.version })}
        />
        <HistoryList
          currentVersion={view.version}
          busy={busy}
          onRestore={(version) => void start({ rollback_to_version: version, base_version: view.version })}
        />
      </div>
    );
  }
  return (
    <>
      {body}
      {dialogs}
    </>
  );
}
