import { useId } from "react";
import type { ChatResponse, Quote, QuoteLine } from "../../api/chat";
import { es } from "../../copy/es";
import { formatCop, formatPercentFromBps } from "../../lib/format";

const t = es.quote;

/** The backend asks ONE question per turn (messages_es.render_clarification); the reply text already asks the first missing field. */
export const ASKED_FIELDS_LIMIT = 1;

function conceptName(line: QuoteLine): string {
  return line.label ?? t.kinds[line.kind] ?? t.kindFallback;
}

/** A code with no matching line is internal: show a neutral label, plus the code only if it is short and plain. */
function unknownName(code: string): string {
  return /^[a-z0-9_]{1,32}$/.test(code) ? `${t.equipmentFallback} (${code})` : t.equipmentFallback;
}

function lineDetail(line: QuoteLine): string | null {
  if (line.unit_amount !== null) return t.unitDetail(line.quantity, line.periods, formatCop(line.unit_amount));
  if (line.rate_bps !== null && line.basis !== null) {
    return t.surchargeDetail(formatPercentFromBps(line.rate_bps), formatCop(line.basis));
  }
  return null;
}

/** Everything below is built from the structured fields of the response, never from its prose. */
export function QuoteDetails({ response }: { response: ChatResponse }) {
  const { quote, availability, missing_fields } = response;
  // Only rentable lines name a code: a package_discount shares the package's code.
  const names = new Map(
    quote?.lines.filter((l) => l.kind === "item" || l.kind === "package").map((l) => [l.code, conceptName(l)]),
  );
  // missing_fields arrives in the backend's priority order; the reply text asks the first one.
  const missing = missing_fields.filter((code) => Object.hasOwn(t.missing, code)).slice(ASKED_FIELDS_LIMIT);
  return (
    <div className="mt-3 space-y-4">
      {quote ? <QuoteTable quote={quote} /> : null}
      {availability ? (
        <Availability availability={availability} quote={quote} names={names} />
      ) : null}
      {missing.length > 0 ? (
        <p className="text-sm text-ink-muted">{t.laterCount(missing.length)}</p>
      ) : null}
    </div>
  );
}

export function QuoteTable({ quote }: { quote: Quote }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="overflow-x-auto">
      <h3 id={headingId} className="text-base font-semibold">
        {t.title}
      </h3>
      <p className="text-sm text-ink-muted">{t.rentalDays(quote.rental_days)}</p>
      <table className="mt-2 w-full min-w-72 text-left text-sm">
        <caption className="sr-only">{t.caption}</caption>
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className="py-1 pr-2 font-semibold">{t.colConcept}</th>
            <th scope="col" className="px-2 py-1 text-right font-semibold">{t.colQuantity}</th>
            <th scope="col" className="py-1 pl-2 text-right font-semibold">{t.colAmount}</th>
          </tr>
        </thead>
        <tbody>
          {quote.lines.map((line) => (
            <tr key={`${line.kind}:${line.code}`} className="border-b border-line align-top">
              <th scope="row" className="py-1 pr-2 font-normal">
                <span className="break-words">{conceptName(line)}</span>
                {lineDetail(line) ? <span className="block text-xs text-ink-muted">{lineDetail(line)}</span> : null}
              </th>
              <td className="px-2 py-1 text-right">{line.quantity}</td>
              <td className="py-1 pl-2 text-right whitespace-nowrap">{formatCop(line.amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" colSpan={2} className="pt-2 pr-2 font-normal">{t.subtotal}</th>
            <td className="pt-2 pl-2 text-right whitespace-nowrap">{formatCop(quote.subtotal)}</td>
          </tr>
          <tr className="text-base font-bold">
            <th scope="row" colSpan={2} className="pr-2">{t.total}</th>
            <td className="pl-2 text-right whitespace-nowrap">{formatCop(quote.total)}</td>
          </tr>
        </tfoot>
      </table>
    </section>
  );
}

function Availability({
  availability,
  quote,
  names,
}: {
  availability: NonNullable<ChatResponse["availability"]>;
  quote: Quote | null;
  names: Map<string, string>;
}) {
  const short = new Map(availability.shortages.map((s) => [s.item_code, s]));
  const rentable = quote?.lines.filter((l) => l.kind === "item" || l.kind === "package") ?? [];
  const codes = [...new Set([...rentable.map((l) => l.code), ...short.keys()])];
  return (
    <div>
      <p className="text-sm font-semibold">{t.availabilityTitle}</p>
      {availability.is_available && codes.length === 0 ? (
        <p className="text-sm">{t.allAvailable}</p>
      ) : (
        <ul className="mt-1 list-disc pl-5 text-sm">
          {codes.map((code) => {
            const s = short.get(code);
            return (
              <li key={code}>
                <span className="break-words">{names.get(code) ?? unknownName(code)}</span>
                {": "}
                {s ? t.shortage(s.requested, s.available) : t.available}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
