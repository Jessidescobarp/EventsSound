import type { ModelInUse } from "../../api/adminAgentConfig";
import { es } from "../../copy/es";
import { microToUsd } from "../../lib/agentConfigForm";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";

const t = es.agentAdmin.card;

/** What the assistant runs on right now. Prices are micro-USD per million tokens. */
export function ModelInUseCard({ model, version }: { model: ModelInUse; version: number }) {
  return (
    <Card>
      <h2 className="text-xl font-semibold">{t.title}</h2>
      <dl className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <Item label={t.provider}>{model.provider}</Item>
        <Item label={t.model}>{model.model}</Item>
        <Item label={t.state}>
          <Badge tone={model.status === "active" ? "brand" : "accent"}>{t.statuses[model.status] ?? model.status}</Badge>
        </Item>
        <Item label={t.config}>{es.agentAdmin.version(version)}</Item>
        <Item label={t.inputPrice}>{t.perMillion(microToUsd(model.input_price_per_mtok))}</Item>
        <Item label={t.outputPrice}>{t.perMillion(microToUsd(model.output_price_per_mtok))}</Item>
      </dl>
      {model.cost_cap_applies ? null : (
        <p className="mt-3 text-sm font-semibold text-warn">
          <span aria-hidden="true">⚠ </span>
          {t.capNotApplied}. <span className="font-normal">{t.capNotAppliedHint}</span>
        </p>
      )}
    </Card>
  );
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="font-medium">{children}</dd>
    </div>
  );
}
