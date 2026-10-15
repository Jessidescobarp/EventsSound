import type { ReactNode } from "react";

export const inputClass =
  "block min-h-11 w-full rounded-control border border-line bg-surface px-3 text-base disabled:bg-surface-alt disabled:text-ink-muted";

/** A labelled control with an optional hint and error; the control gets `describedBy`. */
export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: (props: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}) {
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block font-medium">
        {label}
      </label>
      {children({ id, describedBy, invalid: Boolean(error) })}
      {hint ? (
        <p id={`${id}-hint`} className="text-sm text-ink-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="text-sm font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** The accessibility attributes every control built inside a `Field` carries. */
export function fieldProps(p: { id: string; describedBy: string | undefined; invalid: boolean }) {
  return { id: p.id, "aria-describedby": p.describedBy, "aria-invalid": p.invalid || undefined };
}
