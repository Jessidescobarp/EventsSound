import { fetchMyQuotes } from "../api/records";
import { Pagination } from "../components/records/Pagination";
import { QuotesTable } from "../components/records/QuotesTable";
import { RecordsStatus } from "../components/records/RecordsStatus";
import { ButtonLink } from "../components/ui/Button";
import { Container } from "../components/ui/Container";
import { PageHeader } from "../components/ui/PageHeader";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useNoIndex } from "../hooks/useNoIndex";
import { usePagedRecords } from "../hooks/usePagedRecords";

const t = es.records;

export default function MyQuotesPage() {
  useDocumentTitle(es.titles.myQuotes);
  useNoIndex();
  const { state, failure, setOffset, reload } = usePagedRecords(fetchMyQuotes);
  return (
    <>
      <PageHeader title={t.myTitle} lead={t.myLead} />
      <Container className="py-10">
        <RecordsStatus state={state} failure={failure} onRetry={reload}>
          {(page) =>
            page.total === 0 ? (
              <div className="max-w-xl space-y-4">
                <p className="font-semibold">{t.empty}</p>
                <p className="text-ink-muted">{t.emptyHint}</p>
                <ButtonLink to="/cotizar">{t.emptyCta}</ButtonLink>
              </div>
            ) : (
              <>
                <QuotesTable rows={page.items} showOrigin={false} />
                <Pagination total={page.total} limit={page.limit} offset={page.offset} onChange={setOffset} />
              </>
            )
          }
        </RecordsStatus>
      </Container>
    </>
  );
}
