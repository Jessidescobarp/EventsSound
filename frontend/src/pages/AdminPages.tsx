import { NavLink, Outlet } from "react-router";
import { fetchAdminBookings, fetchAdminQuotes } from "../api/records";
import { BookingsTable } from "../components/records/BookingsTable";
import { Pagination } from "../components/records/Pagination";
import { QuotesTable } from "../components/records/QuotesTable";
import { RecordsStatus } from "../components/records/RecordsStatus";
import { Container } from "../components/ui/Container";
import { PageHeader } from "../components/ui/PageHeader";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useNoIndex } from "../hooks/useNoIndex";
import { usePagedRecords } from "../hooks/usePagedRecords";

const t = es.records;

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `inline-flex min-h-11 items-center rounded-control px-4 text-base font-medium ${
    isActive ? "bg-brand-100 text-brand-900" : "text-ink hover:bg-surface-alt"
  }`;

export function AdminLayout() {
  useDocumentTitle(es.titles.admin);
  useNoIndex();
  return (
    <>
      <PageHeader title={t.adminTitle} lead={t.adminLead} />
      <Container className="py-10">
        <nav aria-label={t.tabsLabel} className="-mx-2 mb-6 flex gap-1">
          <NavLink to="/admin/cotizaciones" className={tabClass}>
            {t.tabQuotes}
          </NavLink>
          <NavLink to="/admin/catalogo" className={tabClass}>
            {es.catalogAdmin.tab}
          </NavLink>
          <NavLink to="/admin/portafolio" className={tabClass}>
            {es.portfolioAdmin.tab}
          </NavLink>
          <NavLink to="/admin/reservas" className={tabClass}>
            {t.tabBookings}
          </NavLink>
        </nav>
        <Outlet />
      </Container>
    </>
  );
}

export function AdminQuotesPage() {
  const { state, failure, setOffset, reload } = usePagedRecords(fetchAdminQuotes);
  return (
    <RecordsStatus state={state} failure={failure} onRetry={reload}>
      {(page) =>
        page.total === 0 ? (
          <p className="font-semibold">{t.empty}</p>
        ) : (
          <>
            <QuotesTable rows={page.items} showOrigin />
            <Pagination total={page.total} limit={page.limit} offset={page.offset} onChange={setOffset} />
          </>
        )
      }
    </RecordsStatus>
  );
}

export function AdminBookingsPage() {
  const { state, failure, setOffset, reload } = usePagedRecords(fetchAdminBookings);
  return (
    <RecordsStatus state={state} failure={failure} onRetry={reload}>
      {(page) =>
        page.total === 0 ? (
          <p className="font-semibold">{t.emptyBookings}</p>
        ) : (
          <>
            <BookingsTable rows={page.items} />
            <Pagination total={page.total} limit={page.limit} offset={page.offset} onChange={setOffset} />
          </>
        )
      }
    </RecordsStatus>
  );
}
