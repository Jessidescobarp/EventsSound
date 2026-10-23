import { useEffect, useId, useState, type FormEvent } from "react";
import { savePackage } from "../../api/adminCatalog";
import type { CatalogItem, ServicePackage } from "../../api/catalog";
import { es } from "../../copy/es";
import { packageInput, type PackageDraft } from "../../lib/catalogForm";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { Field, fieldProps, inputClass } from "./Field";
import { useSave } from "./useSave";

const t = es.catalogAdmin;

type Errors = Partial<Record<"code" | "name" | "discount" | "lines" | "quantity", true>>;

function draftOf(pkg: ServicePackage | null): PackageDraft {
  return pkg
    ? {
        code: pkg.code,
        name: pkg.name,
        discount: String(pkg.discount_bps / 100),
        lines: pkg.items.map((line) => ({ item_code: line.item_code, quantity: String(line.quantity) })),
      }
    : { code: "", name: "", discount: "0", lines: [{ item_code: "", quantity: "1" }] };
}

/** Creates a package (`pkg` null) or edits one; saving replaces its whole list of items. */
export function PackageForm({
  pkg,
  items,
  onSaved,
  onCancel,
  onBusyChange,
}: {
  pkg: ServicePackage | null;
  items: CatalogItem[];
  onSaved: () => void;
  onCancel: () => void;
  /** Lets the hosting dialog block closing while a save is in flight. */
  onBusyChange?: (busy: boolean) => void;
}) {
  const creating = pkg === null;
  const [draft, setDraft] = useState(() => draftOf(pkg));
  const [errors, setErrors] = useState<Errors>({});
  const { busy, failure, run } = useSave(onSaved);
  const base = useId();
  useEffect(() => onBusyChange?.(busy), [busy, onBusyChange]);
  const names = new Map(items.map((item) => [item.code, item.name]));
  const set = (key: "code" | "name" | "discount") => (event: { target: { value: string } }) =>
    setDraft((current) => ({ ...current, [key]: event.target.value }));
  const setLine = (index: number, key: "item_code" | "quantity", value: string) =>
    setDraft((current) => ({
      ...current,
      lines: current.lines.map((line, i) => (i === index ? { ...line, [key]: value } : line)),
    }));

  function submit(event: FormEvent) {
    event.preventDefault();
    const checked = packageInput(draft, creating);
    if (!checked.ok) {
      setErrors(checked.errors);
      return;
    }
    setErrors({});
    void run((token, signal) => savePackage(checked.value, creating, token, signal));
  }

  const err = (key: keyof Errors) => (errors[key] ? t.errors[key] : undefined);
  return (
    <form onSubmit={submit} noValidate aria-label={creating ? t.packageFormNew : t.packageFormEdit} className="space-y-4">
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
        <Field id={`${base}-discount`} label={t.discount} error={err("discount")}>
          {(p) => <input {...fieldProps(p)} value={draft.discount} onChange={set("discount")} inputMode="decimal" className={inputClass} />}
        </Field>
      </div>
      <fieldset className="space-y-3">
        <legend className="font-medium">{t.lines}</legend>
        {err("lines") ? <p className="text-sm font-medium text-danger">{err("lines")}</p> : null}
        {err("quantity") ? <p className="text-sm font-medium text-danger">{err("quantity")}</p> : null}
        {draft.lines.map((line, index) => (
          <div key={index} className="grid items-end gap-3 sm:grid-cols-[1fr_8rem_auto]">
            <Field id={`${base}-line-${index}`} label={t.lineItem}>
              {(p) => (
                <select {...fieldProps(p)} value={line.item_code} onChange={(e) => setLine(index, "item_code", e.target.value)} className={inputClass}>
                  <option value="">{t.pickItem}</option>
                  {items.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field id={`${base}-qty-${index}`} label={t.lineQuantity}>
              {(p) => (
                <input {...fieldProps(p)} value={line.quantity} onChange={(e) => setLine(index, "quantity", e.target.value)} inputMode="numeric" className={inputClass} />
              )}
            </Field>
            <Button
              variant="secondary"
              aria-label={t.removeLine(names.get(line.item_code) ?? t.lineItem)}
              onClick={() => setDraft((c) => ({ ...c, lines: c.lines.filter((_, i) => i !== index) }))}
            >
              ×
            </Button>
          </div>
        ))}
        <Button
          variant="secondary"
          onClick={() => setDraft((c) => ({ ...c, lines: [...c.lines, { item_code: "", quantity: "1" }] }))}
        >
          {t.addLine}
        </Button>
      </fieldset>
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
