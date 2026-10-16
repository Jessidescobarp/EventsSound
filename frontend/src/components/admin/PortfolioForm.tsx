import { useId, useState, type FormEvent } from "react";
import { savePortfolioEvent, type PortfolioEvent } from "../../api/portfolio";
import { es } from "../../copy/es";
import { portfolioInput, type PortfolioDraft, type PortfolioErrors } from "../../lib/portfolioForm";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { Field, fieldProps, inputClass } from "./Field";
import { useSave } from "./useSave";

const t = es.portfolioAdmin;
const failures = es.catalogAdmin.failures;

function draftOf(event: PortfolioEvent | null): PortfolioDraft {
  return event
    ? {
        title: event.title,
        kind: event.kind,
        description: event.description,
        equipment: event.equipment.join("\n"),
        visible: event.visible,
      }
    : { title: "", kind: "", description: "", equipment: "", visible: true };
}

/** Creates an event (`event` null) or edits one; unchecking "visible" hides it from the public page. */
export function PortfolioForm({
  event,
  onSaved,
  onCancel,
}: {
  event: PortfolioEvent | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const creating = event === null;
  const [draft, setDraft] = useState(() => draftOf(event));
  const [errors, setErrors] = useState<PortfolioErrors>({});
  const { busy, failure, run } = useSave(onSaved);
  const base = useId();
  const set = (key: "title" | "kind" | "description" | "equipment") => (e: { target: { value: string } }) =>
    setDraft((current) => ({ ...current, [key]: e.target.value }));

  function submit(submitEvent: FormEvent) {
    submitEvent.preventDefault();
    const checked = portfolioInput(draft);
    if (!checked.ok) {
      setErrors(checked.errors);
      return;
    }
    setErrors({});
    void run((token, signal) => savePortfolioEvent(checked.value, event?.id ?? null, token, signal));
  }

  const err = (key: keyof PortfolioErrors) => (errors[key] ? t.errors[key] : undefined);
  return (
    <form onSubmit={submit} noValidate aria-labelledby={`${base}-title`} className="space-y-4 rounded-card border border-line p-5">
      <h2 id={`${base}-title`} className="text-xl font-semibold">
        {creating ? t.formNew : t.formEdit}
      </h2>
      {Object.keys(errors).length > 0 ? <Alert tone="warn" title={es.catalogAdmin.fixFields} role="alert" /> : null}
      {failure ? <Alert tone="danger" title={failures[failure] ?? failures.unexpected ?? ""} role="alert" /> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id={`${base}-title-input`} label={t.title} error={err("title")}>
          {(p) => <input {...fieldProps(p)} value={draft.title} onChange={set("title")} maxLength={120} className={inputClass} />}
        </Field>
        <Field id={`${base}-kind`} label={t.kind} error={err("kind")}>
          {(p) => <input {...fieldProps(p)} value={draft.kind} onChange={set("kind")} maxLength={40} className={inputClass} />}
        </Field>
      </div>
      <Field id={`${base}-description`} label={t.description} error={err("description")}>
        {(p) => (
          <textarea {...fieldProps(p)} value={draft.description} onChange={set("description")} rows={3} maxLength={500} className={inputClass} />
        )}
      </Field>
      <Field id={`${base}-equipment`} label={t.equipment} hint={t.equipmentHint} error={err("equipment")}>
        {(p) => <textarea {...fieldProps(p)} value={draft.equipment} onChange={set("equipment")} rows={4} className={inputClass} />}
      </Field>
      <label className="flex min-h-11 items-center gap-3 font-medium">
        <input
          type="checkbox"
          checked={draft.visible}
          onChange={(e) => setDraft((current) => ({ ...current, visible: e.target.checked }))}
          className="size-5"
        />
        {t.visible}
      </label>
      <div className="flex flex-wrap gap-3">
        <Button type="submit" disabled={busy}>
          {busy ? es.catalogAdmin.saving : es.catalogAdmin.save}
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          {es.catalogAdmin.cancel}
        </Button>
      </div>
    </form>
  );
}
