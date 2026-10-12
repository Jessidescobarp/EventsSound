import type { ReactNode } from "react";

export function Card({
  as: Tag = "div",
  children,
  className = "",
}: {
  as?: "div" | "article" | "li";
  children: ReactNode;
  className?: string;
}) {
  return (
    <Tag className={`rounded-card border border-line bg-surface p-5 shadow-card ${className}`}>
      {children}
    </Tag>
  );
}
