import type { ReactNode } from "react";

/** Centered column with the 16 px phone gutter (token `gutter`). */
export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`mx-auto w-full max-w-6xl px-gutter sm:px-6 lg:px-8 ${className}`}>{children}</div>
  );
}
