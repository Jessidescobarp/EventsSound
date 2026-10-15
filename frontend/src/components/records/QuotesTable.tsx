import { useId, useState } from "react";
import type { QuoteRecord } from "../../api/records";
import { es } from "../../copy/es";
import { formatCop } from "../../lib/format";
import { QuoteTable } from "../chat/QuoteBreakdown";

const t = es.records;

const DATE = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota" });

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : DATE.format(date);
}

function availability(value: boolean | null): string {
  if (value === null) return t.unknown;
  return value ? t.available : t.withShortages;
}

/** Saved quotes. Every cell is plain text from validated fields; the breakdown reuses the chat table. */
export function QuotesTable({ rows, showOrigin }: { rows: QuoteRecord[]; showOrigin: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-160 text-left text-sm">
        <caption className="sr-only">{t.quotesCaption}</caption>
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className="py-2 pr-3 font-semibold">{t.colDate}</th>
            <th scope="col" className="px-3 py-2 font-semibold">{t.colEvent}</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">{t.colGuests}</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">{t.colTotal}</th>
            <th scope="col" className="px-3 py-2 font-semibold">{t.colAvailability}</th>
            {showOrigin ? <th scope="col" className="px-3 py-2 font-semibold">{t.colOrigin}</th> : null}
            <th scope="col" className="py-2 pl-3 font-semibold">{t.colDetail}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-line align-top">
              <th scope="row" className="py-2 pr-3 font-normal whitespace-nowrap">{when(row.created_at)}</th>
              <td className="px-3 py-2">
                {t.eventTypes[row.event_type] ?? t.eventFallback}
                <span className="block text-xs text-ink-muted">{when(row.event_start)}</span>
              </td>
              <td className="px-3 py-2 text-right">{row.guest_count}</td>
              <td className="px-3 py-2 text-right whitespace-nowrap">{formatCop(row.total_cop)}</td>
              <td className="px-3 py-2">{availability(row.available)}</td>
              {showOrigin ? (
                <td className="px-3 py-2">{row.registered ? t.registered : t.anonymous}</td>
              ) : null}
              <td className="py-2 pl-3">
                <QuoteDetail quote={row.quote} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The breakdown is only built when opened: a page of ten would otherwise render ten tables. */
function QuoteDetail({ quote }: { quote: QuoteRecord["quote"] }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="min-h-11 cursor-pointer font-medium text-brand-700 underline"
      >
        {open ? t.hideDetail : t.showDetail}
      </button>
      <div id={panelId} hidden={!open} className="mt-2 min-w-72">
        {open ? quote ? <QuoteTable quote={quote} /> : <p className="text-ink-muted">{t.detailGone}</p> : null}
      </div>
    </div>
  );
}
