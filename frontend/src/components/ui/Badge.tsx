import type { ReactNode } from "react";

export function Badge({ children, tone = "brand" }: { children: ReactNode; tone?: "brand" | "accent" }) {
  const colors =
    tone === "accent" ? "bg-accent-400 text-ink" : "bg-brand-100 text-brand-900";
  return (
    <span className={`inline-block rounded-full px-3 py-1 text-xs font-semibold ${colors}`}>
      {children}
    </span>
  );
}
