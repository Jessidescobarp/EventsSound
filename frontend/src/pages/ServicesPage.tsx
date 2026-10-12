import { useId, useMemo, useState } from "react";
import { loadCatalog, type Catalog, type CatalogItem, type ServicePackage } from "../api/catalog";
import { Badge } from "../components/ui/Badge";
import { Button, ButtonLink } from "../components/ui/Button";
import { Alert } from "../components/ui/Alert";
import { Card } from "../components/ui/Card";
import { Container } from "../components/ui/Container";
import { PageHeader } from "../components/ui/PageHeader";
import { Spinner } from "../components/ui/Spinner";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useRequest } from "../hooks/useRequest";
import { formatCop, formatPercentFromBps } from "../lib/format";

const OTHER = "__other__";
const t = es.services;

/** Known categories keep their label; anything else is grouped as "Otros". */
function categoryKey(category: string): string {
  return Object.hasOwn(t.categories, category) ? category : OTHER;
}

function categoryLabel(key: string): string {
  return key === OTHER ? t.categoryFallback : (t.categories[key] ?? t.categoryFallback);
}

export default function ServicesPage() {
  useDocumentTitle(es.titles.services);
  const { state, reload } = useRequest(loadCatalog);

  return (
    <>
      <PageHeader title={t.title} lead={t.lead} />
      <Container className="py-10">
        {state.status === "loading" ? (
          <div role="status" className="flex items-center gap-3 text-ink-muted">
            <Spinner />
            <span>{t.loading}</span>
          </div>
        ) : null}
        {state.status === "error" ? (
          <div className="max-w-xl space-y-4">
            <Alert tone="info" title={t.unavailableTitle} role="status">
              {t.unavailableBody}
            </Alert>
            <Button variant="secondary" onClick={reload}>
              {es.common.retry}
            </Button>
          </div>
        ) : null}
        {state.status === "success" ? <CatalogView catalog={state.data} /> : null}
      </Container>
    </>
  );
}

function CatalogView({ catalog }: { catalog: Catalog }) {
  const names = useMemo(() => new Map(catalog.items.map((i) => [i.code, i.name])), [catalog.items]);
  return (
    <div className="space-y-12">
      <PackagesSection packages={catalog.packages} names={names} />
      <ItemsSection items={catalog.items} />
      <div className="rounded-card bg-brand-50 p-6 text-center">
        <p className="text-lg font-semibold text-brand-900">{t.chatCta}</p>
        <div className="mt-4 flex justify-center">
          <ButtonLink to="/cotizar">{t.chatCtaButton}</ButtonLink>
        </div>
      </div>
    </div>
  );
}

function PackagesSection({ packages, names }: { packages: ServicePackage[]; names: Map<string, string> }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="text-2xl font-bold">
        {t.packagesTitle}
      </h2>
      <p className="mt-1 text-ink-muted">{t.packagesLead}</p>
      {packages.length === 0 ? (
        <p className="mt-4 text-ink-muted">{t.emptyPackages}</p>
      ) : (
        <ul aria-labelledby={headingId} className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {packages.map((p) => (
            <Card as="li" key={p.code} className="flex flex-col gap-3">
              <h3 className="text-lg font-semibold text-brand-900">{p.name}</h3>
              {p.discount_bps > 0 ? (
                <div>
                  <Badge tone="accent">{t.discountBadge(formatPercentFromBps(p.discount_bps))}</Badge>
                </div>
              ) : null}
              <p>
                <span className="text-sm text-ink-muted">{t.fromLabel}</span>{" "}
                <span className="text-xl font-bold">{formatCop(p.base_price_cop)}</span>{" "}
                <span className="text-sm text-ink-muted">{t.perDay}</span>
              </p>
              <div>
                <p className="text-sm font-semibold">{t.includesLabel}</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-muted">
                  {p.items.map((m) => (
                    <li key={m.item_code}>{t.memberLine(m.quantity, names.get(m.item_code) ?? m.item_code)}</li>
                  ))}
                </ul>
              </div>
            </Card>
          ))}
        </ul>
      )}
    </section>
  );
}

function ItemsSection({ items }: { items: CatalogItem[] }) {
  const headingId = useId();
  const selectId = useId();
  const [selected, setSelected] = useState("");

  const keys = useMemo(() => {
    const present = new Set(items.map((i) => categoryKey(i.category)));
    const known = Object.keys(t.categories).filter((k) => present.has(k));
    return present.has(OTHER) ? [...known, OTHER] : known;
  }, [items]);

  const visible = selected ? items.filter((i) => categoryKey(i.category) === selected) : items;

  return (
    <section aria-labelledby={headingId}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h2 id={headingId} className="text-2xl font-bold">
          {t.itemsTitle}
        </h2>
        {items.length > 0 ? (
          <div className="flex flex-col gap-1">
            <label htmlFor={selectId} className="text-sm font-semibold">
              {t.categoryFilterLabel}
            </label>
            <select
              id={selectId}
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
              className="min-h-11 rounded-control border border-line bg-surface px-3 text-base"
            >
              <option value="">{t.categoryAll}</option>
              {keys.map((key) => (
                <option key={key} value={key}>
                  {categoryLabel(key)}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>
      {items.length === 0 ? (
        <p className="mt-4 text-ink-muted">{t.emptyItems}</p>
      ) : (
        <ul aria-labelledby={headingId} className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((i) => (
            <Card as="li" key={i.code} className="flex flex-col gap-2">
              <div>
                <Badge>{categoryLabel(categoryKey(i.category))}</Badge>
              </div>
              <h3 className="text-lg font-semibold">{i.name}</h3>
              <p>
                <span className="text-xl font-bold">{formatCop(i.unit_price_cop)}</span>{" "}
                <span className="text-sm text-ink-muted">{t.perDay}</span>
              </p>
              <p className="text-sm text-ink-muted">{t.stockLabel(i.stock_quantity)}</p>
            </Card>
          ))}
        </ul>
      )}
    </section>
  );
}
