import type { BookingRecord } from "../../api/records";
import { es } from "../../copy/es";

const t = es.records;

const DATE = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota" });

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : DATE.format(date);
}

/** One row per equipment item of a booking (the backend table is flat). */
export function BookingsTable({ rows }: { rows: BookingRecord[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-160 text-left text-sm">
        <caption className="sr-only">{t.bookingsCaption}</caption>
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className="py-2 pr-3 font-semibold">{t.colCode}</th>
            <th scope="col" className="px-3 py-2 font-semibold">{t.colItem}</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">{t.colQuantity}</th>
            <th scope="col" className="px-3 py-2 font-semibold">{t.colStart}</th>
            <th scope="col" className="px-3 py-2 font-semibold">{t.colEnd}</th>
            <th scope="col" className="py-2 pl-3 font-semibold">{t.colStatus}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.booking_code}:${row.item_code}`} className="border-b border-line align-top">
              <th scope="row" className="py-2 pr-3 font-normal whitespace-nowrap">{row.booking_code}</th>
              <td className="px-3 py-2 break-words">{row.item_code}</td>
              <td className="px-3 py-2 text-right">{row.quantity}</td>
              <td className="px-3 py-2 whitespace-nowrap">{when(row.starts_at)}</td>
              <td className="px-3 py-2 whitespace-nowrap">{when(row.ends_at)}</td>
              <td className="py-2 pl-3">{t.statuses[row.status] ?? t.statusFallback}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
