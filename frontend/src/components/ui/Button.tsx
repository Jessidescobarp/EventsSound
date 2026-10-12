import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router";

type Variant = "primary" | "secondary" | "inverse";

const BASE =
  "inline-flex min-h-11 items-center justify-center rounded-control px-5 py-2.5 text-base font-semibold " +
  "transition-colors disabled:cursor-not-allowed disabled:opacity-60";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700",
  secondary: "border border-brand-600 bg-surface text-brand-700 hover:bg-brand-50",
  inverse: "bg-white text-brand-900 hover:bg-brand-100",
};

export function buttonClasses(variant: Variant): string {
  return `${BASE} ${VARIANTS[variant]}`;
}

export function Button({
  variant = "primary",
  type = "button",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; children: ReactNode }) {
  return (
    <button type={type} className={buttonClasses(variant)} {...rest}>
      {children}
    </button>
  );
}

export function ButtonLink({
  variant = "primary",
  ...rest
}: LinkProps & { variant?: Variant }) {
  return <Link className={buttonClasses(variant)} {...rest} />;
}
