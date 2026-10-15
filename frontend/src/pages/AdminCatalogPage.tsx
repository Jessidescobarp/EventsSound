import { useState } from "react";
import { loadCatalog, type CatalogItem, type ServicePackage } from "../api/catalog";
import { ItemForm } from "../components/admin/ItemForm";
import { PackageForm } from "../components/admin/PackageForm";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Spinner } from "../components/ui/Spinner";
import { es } from "../copy/es";
import { useRequest } from "../hooks/useRequest";
import { formatCop } from "../lib/format";

const t = es.catalogAdmin;

type Editing =
  | { kind: "item"; item: CatalogItem | null }
  | { kind: "package"; pkg: ServicePackage | null }
  | null;

export function AdminCatalogPage() {
  const { state, reload } = useRequest(loadCatalog);
  const [editing, setEditing] = useState<Editing>(null);
  const [saved, setSaved] = useState(false);

  const open = (next: Editing) => {
    setSaved(false);
    setEditing(next);
  };
  const onSaved = () => {
    setEditing(null);
    setSaved(true);
    reload();
  };

  return (
    <div className="space-y-8">
      <p className="max-w-3xl text-ink-muted">{t.lead}</p>
      {saved ? (
        <Alert tone="info" title={t.saved} role="status">
          {t.savedBody}
        </Alert>
      ) : null}
      {editing?.kind === "item" ? (
        <ItemForm key={editing.item?.code ?? "new"} item={editing.item} onSaved={onSaved} onCancel={() => setEditing(null)} />
      ) : null}
      {editing?.kind === "package" && state.status === "success" ? (
        <PackageForm
          key={editing.pkg?.code ?? "new"}
          pkg={editing.pkg}
          items={state.data.items}
          onSaved={onSaved}
          onCancel={() => setEditing(null)}
        />
      ) : null}
      {state.status === "loading" ? (
        <div role="status" className="flex items-center gap-3 text-ink-muted">
          <Spinner />
          <span>{es.records.loading}</span>
        </div>
      ) : null}
      {state.status === "error" ? (
        <div className="max-w-xl space-y-4">
          <Alert tone="warn" title={es.records.errorTitle} role="alert">
            {es.records.errorBody}
          </Alert>
          <Button variant="secondary" onClick={reload}>
            {es.common.retry}
          </Button>
        </div>
      ) : null}
      {state.status === "success" ? (
        <>
          <ItemsSection items={state.data.items} onNew={() => open({ kind: "item", item: null })} onEdit={(item) => open({ kind: "item", item })} />
          <PackagesSection
            packages={state.data.packages}
            onNew={() => open({ kind: "package", pkg: null })}
            onEdit={(pkg) => open({ kind: "package", pkg })}
          />
        </>
      ) : null}
    </div>
  );
}

function ItemsSection({
  items,
  onNew,
  onEdit,
}: {
  items: CatalogItem[];
  onNew: () => void;
  onEdit: (item: CatalogItem) => void;
}) {
  return (
    <section aria-labelledby="admin-items" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="admin-items" className="text-xl font-semibold">
          {t.itemsTitle}
        </h2>
        <Button onClick={onNew}>{t.newItem}</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-160 text-left text-sm">
          <caption className="sr-only">{t.itemsCaption}</caption>
          <thead>
            <tr className="border-b border-line">
              <th scope="col" className="py-2 pr-3 font-semibold">{t.colName}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{t.colCategory}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{t.colStock}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{t.colPrice}</th>
              <th scope="col" className="py-2 pl-3 font-semibold">{t.colActions}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.code} className="border-b border-line">
                <th scope="row" className="py-2 pr-3 font-normal">
                  {item.name}
                  <span className="block text-xs text-ink-muted">{item.code}</span>
                </th>
                <td className="px-3 py-2">{es.services.categories[item.category] ?? es.services.categoryFallback}</td>
                <td className="px-3 py-2 text-right">{item.stock_quantity}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">{formatCop(item.unit_price_cop)}</td>
                <td className="py-2 pl-3">
                  <button
                    type="button"
                    aria-label={t.editLabel(item.name)}
                    onClick={() => onEdit(item)}
                    className="min-h-11 cursor-pointer font-medium text-brand-700 underline"
                  >
                    {t.edit}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PackagesSection({
  packages,
  onNew,
  onEdit,
}: {
  packages: ServicePackage[];
  onNew: () => void;
  onEdit: (pkg: ServicePackage) => void;
}) {
  return (
    <section aria-labelledby="admin-packages" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="admin-packages" className="text-xl font-semibold">
          {t.packagesTitle}
        </h2>
        <Button onClick={onNew}>{t.newPackage}</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-160 text-left text-sm">
          <caption className="sr-only">{t.packagesCaption}</caption>
          <thead>
            <tr className="border-b border-line">
              <th scope="col" className="py-2 pr-3 font-semibold">{t.colName}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{t.colMembers}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{t.colDiscount}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{t.colPrice}</th>
              <th scope="col" className="py-2 pl-3 font-semibold">{t.colActions}</th>
            </tr>
          </thead>
          <tbody>
            {packages.map((pkg) => (
              <tr key={pkg.code} className="border-b border-line">
                <th scope="row" className="py-2 pr-3 font-normal">
                  {pkg.name}
                  <span className="block text-xs text-ink-muted">{pkg.code}</span>
                </th>
                <td className="px-3 py-2 text-right">{pkg.items.length}</td>
                <td className="px-3 py-2 text-right">{pkg.discount_bps / 100}%</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">{formatCop(pkg.base_price_cop)}</td>
                <td className="py-2 pl-3">
                  <button
                    type="button"
                    aria-label={t.editLabel(pkg.name)}
                    onClick={() => onEdit(pkg)}
                    className="min-h-11 cursor-pointer font-medium text-brand-700 underline"
                  >
                    {t.edit}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
