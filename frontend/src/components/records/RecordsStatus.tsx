import type { ReactNode } from "react";
import type { RecordsFailure } from "../../api/records";
import type { RequestState } from "../../hooks/useRequest";
import { es } from "../../copy/es";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { Spinner } from "../ui/Spinner";

const t = es.records;

/** Loading, error and success shells shared by the three lists. */
export function RecordsStatus<T>({
  state,
  failure,
  onRetry,
  children,
}: {
  state: RequestState<T>;
  failure: RecordsFailure | null;
  onRetry: () => void;
  children: (data: T) => ReactNode;
}) {
  if (state.status === "loading") {
    return (
      <div role="status" className="flex items-center gap-3 text-ink-muted">
        <Spinner />
        <span>{t.loading}</span>
      </div>
    );
  }
  if (state.status === "error") {
    if (failure === "unauthenticated") {
      return (
        <Alert tone="info" title={t.sessionEnded} role="status" />
      );
    }
    const unavailable = failure === "unavailable";
    return (
      <div className="max-w-xl space-y-4">
        <Alert tone="warn" title={unavailable ? t.unavailableTitle : t.errorTitle} role="alert">
          {t.errorBody}
        </Alert>
        <Button variant="secondary" onClick={onRetry}>
          {es.common.retry}
        </Button>
      </div>
    );
  }
  return <>{children(state.data)}</>;
}
