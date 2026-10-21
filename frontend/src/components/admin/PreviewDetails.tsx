import type { Diff, DiffValue, Preview } from "../../api/adminAgentConfig";
import { es } from "../../copy/es";
import { microToUsd } from "../../lib/agentConfigForm";

const t = es.agentAdmin;

const ICONS = { info: "ℹ", warning: "⚠", danger: "⛔" } as const;
const SEVERITY_CLASS = {
  info: "border-info/30 bg-info-soft text-info",
  warning: "border-warn/30 bg-warn-soft text-warn",
  danger: "border-danger/30 bg-danger-soft text-danger",
} as const;

/** Plain text for a diff value: the cost cap in USD, an empty value spelled out, everything else as is. */
export function showValue(field: string, value: DiffValue): string {
  if (value === null || value === "") return t.empty;
  if (field === "daily_cost_cap_micro_usd" && typeof value === "number") return `${microToUsd(value)} USD`;
  if (field === "tone") return t.tones[String(value)] ?? String(value);
  if (field === "off_topic_policy") return t.policies[String(value)] ?? String(value);
  return String(value);
}

/** Field-by-field changes, old to new. Values are text nodes, never markup. */
export function DiffList({ diff }: { diff: Diff }) {
  return (
    <ul className="space-y-2">
      {Object.entries(diff).map(([field, [from, to]]) => (
        <li key={field} className="text-sm">
          <span className="font-semibold">{t.fields[field] ?? field}</span>
          <span className="block whitespace-pre-wrap break-words text-ink-muted">
            {t.diffFrom}: {showValue(field, from)}
          </span>
          <span className="block whitespace-pre-wrap break-words">
            {t.diffTo}: {showValue(field, to)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Diff, risk warnings (icon and text, never colour alone) and the cost estimate of a preview. */
export function PreviewDetails({ preview }: { preview: Preview }) {
  const estimate = preview.max_daily_cost_estimate_micro_usd;
  return (
    <div className="space-y-4">
      <DiffList diff={preview.diff} />
      <ul className="space-y-2">
        {preview.warnings.map((w) => (
          <li key={w.code} className={`rounded-control border px-3 py-2 text-sm ${SEVERITY_CLASS[w.severity]}`}>
            <span aria-hidden="true">{ICONS[w.severity]} </span>
            <span className="font-semibold">{t.severity[w.severity]}: </span>
            {w.message_es}
          </li>
        ))}
      </ul>
      <p className="text-sm font-medium">{estimate === null ? t.estimateUnknown : t.estimate(microToUsd(estimate))}</p>
    </div>
  );
}
