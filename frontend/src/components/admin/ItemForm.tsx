import { useEffect, useId, useState, type FormEvent } from "react";
import { saveItem } from "../../api/adminCatalog";
import type { CatalogItem } from "../../api/catalog";
import { es } from "../../copy/es";
import { CATEGORIES, itemInput, type ItemDraft } from "../../lib/catalogForm";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { Field, fieldProps, inputClass } from "./Field";
import { useSave } from "./useSave";

const t = es.catalogAdmin;

function draftOf(item: CatalogItem | null): ItemDraft {
  return item
    ? {
        code: item.code,
        name: item.name,
        category: item.category,
        stock: String(item.stock_quantity),
        price: String(item.unit_price_cop),
      }
    : { code: "", name: "", category: "sound", stock: "0", price: "0" };
}

/** Creates an item (`item` null) or edits one. The code is fixed once it exists. */
export function ItemForm({
  item,
  onSaved,
  onCancel,
  onBusyChange,
}: {
  item: CatalogItem | null;
  onSaved: () => void;
  onCancel: () => void;
  /** Lets the hosting dialog block closing while a save is in flight. */
  onBusyChange?: (busy: boolean) => void;
}) {
  const creating = item === null;
  const [draft, setDraft] = useState(() => draftOf(item));
  const [errors, setErrors] = useState<Partial<Record<keyof ItemDraft, true>>>({});
  const { busy, failure, run } = useSave(onSaved);
  const base = useId();
  useEffect(() => onBusyChange?.(busy), [busy, onBusyChange]);
  const set = (key: keyof ItemDraft) => (event: { target: { value: string } }) =>
    setDraft((current) => ({ ...current, [key]: event.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    const checked = itemInput(draft, creating);
    if (!checked.ok) {
      setErrors(checked.errors);
      return;
    }
    setErrors({});
    void run((token, signal) => saveItem(checked.value, creating, token, signal));
  }

  const err = (key: keyof ItemDraft) => (errors[key] ? t.errors[key] : undefined);
  return (
    <form onSubmit={submit} noValidate aria-label={creating ? t.itemFormNew : t.itemFormEdit} className="space-y-4">
      {Object.keys(errors).length > 0 ? <Alert tone="warn" title={t.fixFields} role="alert" /> : null}
      {failure ? <Alert tone="danger" title={t.failures[failure] ?? t.failures.unexpected ?? ""} role="alert" /> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id={`${base}-code`} label={t.code} hint={creating ? t.codeHint : undefined} error={err("code")}>
          {(p) => (
            <input {...fieldProps(p)} value={draft.code} onChange={set("code")} disabled={!creating} autoComplete="off" className={inputClass} />
          )}
        </Field>
        <Field id={`${base}-name`} label={t.name} error={err("name")}>
          {(p) => <input {...fieldProps(p)} value={draft.name} onChange={set("name")} maxLength={120} className={inputClass} />}
        </Field>
        <Field id={`${base}-category`} label={t.category} error={err("category")}>
          {(p) => (
            <select {...fieldProps(p)} value={draft.category} onChange={set("category")} className={inputClass}>
              {CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {es.services.categories[category]}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field id={`${base}-stock`} label={t.stock} hint={t.stockHint} error={err("stock")}>
          {(p) => <input {...fieldProps(p)} value={draft.stock} onChange={set("stock")} inputMode="numeric" className={inputClass} />}
        </Field>
        <Field id={`${base}-price`} label={t.price} error={err("price")}>
          {(p) => <input {...fieldProps(p)} value={draft.price} onChange={set("price")} inputMode="numeric" className={inputClass} />}
        </Field>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button type="submit" disabled={busy}>
          {busy ? t.saving : t.save}
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          {t.cancel}
        </Button>
      </div>
    </form>
  );
}
