import { fetchSecurityEvents, SECURITY_KINDS } from "../api/security";
import { Pagination } from "../components/records/Pagination";
import { RecordsStatus } from "../components/records/RecordsStatus";
import { es } from "../copy/es";
import { usePagedRecords } from "../hooks/usePagedRecords";
import { formatDateTime } from "../lib/format";

const t = es.securityAdmin;

/** Security events: plain text from validated fields. The client column is a hash, never an IP. */
export function AdminSecurityPage() {
  const { state, failure, setOffset, reload } = usePagedRecords(fetchSecurityEvents);
  return (
    <div className="space-y-4">
      <p className="max-w-prose text-ink-muted">{t.lead}</p>
      <RecordsStatus state={state} failure={failure} onRetry={reload}>
        {(page) => (
          <>
            <p className="font-semibold">
              {t.summary}:{" "}
              {SECURITY_KINDS.map((kind) => `${t.kinds[kind]}: ${page.last_24h[kind]}`).join(" · ")}
            </p>
            {page.total === 0 ? (
              <p className="font-semibold">{t.empty}</p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-96 text-left text-sm">
                    <caption className="sr-only">{t.caption}</caption>
                    <thead>
                      <tr className="border-b border-line">
                        <th scope="col" className="py-2 pr-3 font-semibold">{t.colDate}</th>
                        <th scope="col" className="px-3 py-2 font-semibold">{t.colKind}</th>
                        <th scope="col" className="py-2 pl-3 font-semibold">{t.colClient}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {page.items.map((row) => (
                        <tr key={row.id} className="border-b border-line">
                          <th scope="row" className="py-2 pr-3 font-normal whitespace-nowrap">{formatDateTime(row.at)}</th>
                          <td className="px-3 py-2">{t.kinds[row.kind]}</td>
                          <td className="py-2 pl-3 font-mono">{row.client}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pagination total={page.total} limit={page.limit} offset={page.offset} onChange={setOffset} />
              </>
            )}
          </>
        )}
      </RecordsStatus>
    </div>
  );
}
