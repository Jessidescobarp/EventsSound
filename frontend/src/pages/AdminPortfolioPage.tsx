import { useCallback, useState } from "react";
import { loadAllPortfolio, type PortfolioEvent } from "../api/portfolio";
import { useAuth } from "../auth/authContext";
import { PortfolioForm } from "../components/admin/PortfolioForm";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Spinner } from "../components/ui/Spinner";
import { es } from "../copy/es";
import { useRequest } from "../hooks/useRequest";

const t = es.portfolioAdmin;

export function AdminPortfolioPage() {
  const { session } = useAuth();
  const token = session?.token ?? "";
  const load = useCallback((signal: AbortSignal) => loadAllPortfolio(token, signal), [token]);
  const { state, reload } = useRequest(load);
  const [editing, setEditing] = useState<{ event: PortfolioEvent | null } | null>(null);
  const [saved, setSaved] = useState(false);

  const open = (event: PortfolioEvent | null) => {
    setSaved(false);
    setEditing({ event });
  };

  return (
    <div className="space-y-8">
      <p className="max-w-3xl text-ink-muted">{t.lead}</p>
      {saved ? <Alert tone="info" title={es.catalogAdmin.saved} role="status" /> : null}
      {editing ? (
        <PortfolioForm
          key={editing.event?.id ?? "new"}
          event={editing.event}
          onSaved={() => {
            setEditing(null);
            setSaved(true);
            reload();
          }}
          onCancel={() => setEditing(null)}
        />
      ) : null}
      {state.status === "loading" ? (
        <div role="status" className="flex items-center gap-3 text-ink-muted">
          <Spinner />
          <span>{es.records.loading}</span>
        </div>
      ) : null}
      {state.status === "error" ? (
        <div className="max-w-xl space-y-4">
          <Alert tone="warn" title={es.records.errorTitle} role="alert">
            {es.records.errorBody}
          </Alert>
          <Button variant="secondary" onClick={reload}>
            {es.common.retry}
          </Button>
        </div>
      ) : null}
      {state.status === "success" ? (
        <section className="space-y-4">
          <Button onClick={() => open(null)}>{t.newEvent}</Button>
          <div className="overflow-x-auto">
            <table className="w-full min-w-160 text-left text-sm">
              <caption className="sr-only">{t.caption}</caption>
              <thead>
                <tr className="border-b border-line">
                  <th scope="col" className="py-2 pr-3 font-semibold">{t.colTitle}</th>
                  <th scope="col" className="px-3 py-2 font-semibold">{t.colKind}</th>
                  <th scope="col" className="px-3 py-2 font-semibold">{t.colVisible}</th>
                  <th scope="col" className="py-2 pl-3 font-semibold">{es.catalogAdmin.colActions}</th>
                </tr>
              </thead>
              <tbody>
                {state.data.map((event) => (
                  <tr key={event.id} className="border-b border-line">
                    <th scope="row" className="py-2 pr-3 font-normal break-words">{event.title}</th>
                    <td className="px-3 py-2">{event.kind}</td>
                    <td className="px-3 py-2">
                      <Badge tone={event.visible ? "brand" : "accent"}>{event.visible ? t.shown : t.hidden}</Badge>
                    </td>
                    <td className="py-2 pl-3">
                      <button
                        type="button"
                        aria-label={es.catalogAdmin.editLabel(event.title)}
                        onClick={() => open(event)}
                        className="min-h-11 cursor-pointer font-medium text-brand-700 underline"
                      >
                        {es.catalogAdmin.edit}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
