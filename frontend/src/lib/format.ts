const COP = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

const PERCENT = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 });

const DATE_TIME = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota" });

/** An ISO timestamp as a Bogota date and time, or a dash when it is not a date. */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : DATE_TIME.format(date);
}

/** Whole-peso amounts, e.g. 120000 -> "$ 120.000". */
export function formatCop(amount: number): string {
  return COP.format(amount);
}

/** Basis points as a percentage without a space, e.g. 1050 -> "10,5%". */
export function formatPercentFromBps(bps: number): string {
  return `${PERCENT.format(bps / 100)}%`;
}
