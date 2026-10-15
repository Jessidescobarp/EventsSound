import { Button } from "../ui/Button";
import { es } from "../../copy/es";

const t = es.records;

/** Previous / next with the position, driven by the page the server actually returned. */
export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor(offset / limit) + 1;
  return (
    <nav aria-label={t.pagination} className="mt-4 flex flex-wrap items-center gap-3">
      <Button variant="secondary" disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        {t.previous}
      </Button>
      <span role="status" className="text-sm text-ink-muted">
        {t.pageOf(page, pages)} · {t.totalRows(total)}
      </span>
      <Button variant="secondary" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
        {t.next}
      </Button>
    </nav>
  );
}
