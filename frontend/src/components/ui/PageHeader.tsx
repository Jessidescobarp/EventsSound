import type { ReactNode } from "react";
import { Container } from "./Container";

/** Page title band: the one h1 of each page. */
export function PageHeader({ title, lead, children }: { title: string; lead?: string; children?: ReactNode }) {
  return (
    <div className="bg-brand-50">
      <Container className="py-10 sm:py-14">
        <h1 className="font-display text-3xl font-bold tracking-tight text-brand-900 sm:text-4xl">
          {title}
        </h1>
        {lead ? <p className="mt-3 max-w-3xl text-lg text-ink-muted">{lead}</p> : null}
        {children}
      </Container>
    </div>
  );
}
