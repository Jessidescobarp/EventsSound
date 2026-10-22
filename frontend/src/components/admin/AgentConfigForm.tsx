import { useId, useState, type FormEvent } from "react";
import {
  MAX_TEXT_CHARS,
  OFF_TOPIC_POLICIES,
  TEXT_FIELDS,
  TONES,
  type AgentConfig,
  type AgentConfigView,
} from "../../api/adminAgentConfig";
import { es } from "../../copy/es";
import { draftOf, evaluateDraft, microToUsd, type AgentDraft, type FormResult } from "../../lib/agentConfigForm";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { Field, fieldProps, inputClass } from "./Field";

const t = es.agentAdmin;
const number = new Intl.NumberFormat("es-CO");

/** Hint under a text field: the rules that apply to it plus the character counter. */
const textHint = (field: (typeof TEXT_FIELDS)[number], value: string) =>
  `${t.textRules}${field === "welcome_message" ? t.noMoneyRule : t.noDigitsRule} ${t.counter(Array.from(value).length, MAX_TEXT_CHARS)}`;

/** Edits the stored config. Only changed fields reach `onReview`; the server stays the authority. */
export function AgentConfigForm({
  view,
  busy,
  onReview,
}: {
  view: AgentConfigView;
  busy: boolean;
  onReview: (changes: Partial<AgentConfig>) => void;
}) {
  const [draft, setDraft] = useState(() => draftOf(view.config));
  const [problems, setProblems] = useState<FormResult["problems"]>({});
  const [unchanged, setUnchanged] = useState(false);
  const base = useId();
  const set = (key: keyof AgentDraft) => (event: { target: { value: string } }) =>
    setDraft((current) => ({ ...current, [key]: event.target.value }));
  const err = (key: keyof AgentDraft) => (problems[key] ? t.problems[problems[key]] : undefined);

  function submit(event: FormEvent) {
    event.preventDefault();
    const result = evaluateDraft(draft, view);
    setProblems(result.problems);
    const changed = Object.keys(result.changes).length > 0;
    setUnchanged(!changed && Object.keys(result.problems).length === 0);
    if (changed && Object.keys(result.problems).length === 0) onReview(result.changes);
  }

  const { ceilings } = view;
  const outOfBounds = view.defaults_out_of_bounds.map((f) => t.fields[f] ?? f).join(", ");
  const select = (key: "tone" | "off_topic_policy", options: readonly string[], labels: Record<string, string>) => (
    <Field id={`${base}-${key}`} label={t.fields[key] ?? key}>
      {(p) => (
        <select {...fieldProps(p)} value={draft[key]} onChange={set(key)} className={inputClass}>
          {options.map((o) => (
            <option key={o} value={o}>{labels[o] ?? o}</option>
          ))}
        </select>
      )}
    </Field>
  );
  const numeric = (key: "daily_token_cap" | "daily_cost_cap_usd" | "chat_rate_limit_per_minute", ceiling: string) => (
    <Field id={`${base}-${key}`} label={t.fields[key] ?? key} hint={t.ceiling(ceiling)} error={err(key)}>
      {(p) => <input {...fieldProps(p)} value={draft[key]} onChange={set(key)} inputMode="decimal" autoComplete="off" className={inputClass} />}
    </Field>
  );

  return (
    <form onSubmit={submit} noValidate aria-label={t.tab} className="space-y-4 rounded-card border border-line p-5">
      {outOfBounds ? <Alert tone="warn" title={t.outOfBounds(outOfBounds)} role="note" /> : null}
      {Object.keys(problems).length > 0 ? <Alert tone="warn" title={t.fixFields} role="alert" /> : null}
      {unchanged ? <Alert tone="info" title={t.noChanges} role="status" /> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        {select("tone", TONES, t.tones)}
        {select("off_topic_policy", OFF_TOPIC_POLICIES, t.policies)}
      </div>
      {TEXT_FIELDS.map((key) => (
        <Field key={key} id={`${base}-${key}`} label={t.fields[key] ?? key} hint={textHint(key, draft[key])} error={err(key)}>
          {(p) => <textarea {...fieldProps(p)} value={draft[key]} onChange={set(key)} rows={3} className={`${inputClass} py-2`} />}
        </Field>
      ))}
      <Field id={`${base}-llm_model`} label={t.fields.llm_model ?? "llm_model"} error={err("llm_model")}>
        {(p) => (
          <select {...fieldProps(p)} value={draft.llm_model} onChange={set("llm_model")} className={inputClass}>
            {(view.allowed_models.includes(draft.llm_model) ? view.allowed_models : [draft.llm_model, ...view.allowed_models]).map((m) => (
              <option key={m} value={m}>{view.free_models.includes(m) ? t.freeModelOption(m) : view.paid_models.includes(m) ? t.paidModelOption(m) : m}</option>
            ))}
          </select>
        )}
      </Field>
      <div className="grid gap-4 sm:grid-cols-3">
        {numeric("daily_token_cap", number.format(ceilings.max_daily_tokens))}
        {numeric("daily_cost_cap_usd", `${microToUsd(ceilings.max_daily_cost_micro_usd)} USD`)}
        {numeric("chat_rate_limit_per_minute", number.format(ceilings.max_rate_limit_per_minute))}
      </div>
      <Button type="submit" disabled={busy}>
        {busy ? t.reviewing : t.review}
      </Button>
    </form>
  );
}
