import type { ReactNode } from "react";

type Tone = "info" | "warn" | "danger";

const TONES: Record<Tone, string> = {
  info: "border-info/30 bg-info-soft text-info",
  warn: "border-warn/30 bg-warn-soft text-warn",
  danger: "border-danger/30 bg-danger-soft text-danger",
};

/** Static callout. The caller chooses the ARIA role (status, alert, note) when needed. */
export function Alert({
  tone,
  title,
  children,
  role,
}: {
  tone: Tone;
  title: string;
  children?: ReactNode;
  role?: "status" | "alert" | "note";
}) {
  return (
    <div role={role} className={`rounded-control border px-4 py-3 ${TONES[tone]}`}>
      <p className="font-semibold">{title}</p>
      {children ? <div className="mt-1 text-sm">{children}</div> : null}
    </div>
  );
}
