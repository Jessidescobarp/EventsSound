import { useCallback } from "react";
import { fetchAgentHistory, type Diff } from "../../api/adminAgentConfig";
import { useAuth } from "../../auth/authContext";
import { es } from "../../copy/es";
import { useRequest } from "../../hooks/useRequest";
import { formatDateTime } from "../../lib/format";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { showValue } from "./PreviewDetails";

const t = es.agentAdmin;
const h = t.history;
const MAX_VALUE_CHARS = 40;

const clip = (text: string) => (text.length > MAX_VALUE_CHARS ? `${text.slice(0, MAX_VALUE_CHARS)}…` : text);
/** One line per change, plain text: "Tono: Cercano → Formal". */
const compact = (diff: Diff) =>
  Object.entries(diff).map(([field, [from, to]]) => `${t.fields[field] ?? field}: ${clip(showValue(field, from))} → ${clip(showValue(field, to))}`);

/** Saved versions, newest first, each with a way to restore it (the same preview and double confirmation). */
export function HistoryList({
  currentVersion,
  busy,
  onRestore,
}: {
  /** Reloads the list when it changes (a new version was applied). */
  currentVersion: number;
  busy: boolean;
  onRestore: (version: number) => void;
}) {
  const { session } = useAuth();
  const token = session?.token ?? "";
  const load = useCallback((signal: AbortSignal) => fetchAgentHistory(token, signal), [token, currentVersion]); // eslint-disable-line react-hooks/exhaustive-deps
  const { state } = useRequest(load);

  return (
    <section aria-labelledby="agent-history" className="space-y-3">
      <h2 id="agent-history" className="text-xl font-semibold">
        {h.title}
      </h2>
      {state.status === "error" ? <Alert tone="warn" title={h.error} role="alert" /> : null}
      {state.status === "success" && state.data.length === 0 ? <p className="font-semibold">{h.empty}</p> : null}
      {state.status === "success" && state.data.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-160 text-left text-sm">
            <caption className="sr-only">{h.caption}</caption>
            <thead>
              <tr className="border-b border-line">
                {[h.colVersion, h.colDate, h.colAuthor, h.colAction, h.colNote, h.colChanges, h.colActions].map((label) => (
                  <th key={label} scope="col" className="px-2 py-2 font-semibold">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {state.data.map((row) => (
                <tr key={row.version} className="border-b border-line align-top">
                  <th scope="row" className="px-2 py-2 font-semibold">{row.version}</th>
                  <td className="px-2 py-2 whitespace-nowrap">{formatDateTime(row.created_at)}</td>
                  <td className="px-2 py-2 font-mono">{row.created_by?.slice(0, 8) ?? "—"}</td>
                  <td className="px-2 py-2">{h.actions[row.action]}</td>
                  <td className="px-2 py-2 break-words">{row.note ?? "—"}</td>
                  <td className="px-2 py-2">
                    <ul className="space-y-1">
                      {compact(row.diff).map((line) => (
                        <li key={line} className="break-words">{line}</li>
                      ))}
                    </ul>
                  </td>
                  <td className="px-2 py-2">
                    {row.version === currentVersion ? (
                      h.current
                    ) : (
                      <Button variant="secondary" aria-label={h.restoreLabel(row.version)} disabled={busy} onClick={() => onRestore(row.version)}>
                        {h.restore}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
