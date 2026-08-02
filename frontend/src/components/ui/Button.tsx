import type { ButtonHTMLAttributes, ReactNode } from "react";
import { classNames } from "@/lib/format";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50 shadow-sm",
  secondary:
    "bg-white text-ink-800 border border-ink-200 hover:bg-ink-50 disabled:text-ink-400",
  ghost: "text-ink-600 hover:bg-ink-100 hover:text-ink-900 disabled:text-ink-300",
  danger:
    "bg-white text-critical border border-critical/30 hover:bg-critical/5 disabled:opacity-50",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  children,
  className,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      // A button that is busy must not be clickable twice — double-submitting
      // a scan is the most likely accidental duplicate in this app.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={classNames(
        "inline-flex items-center justify-center rounded-lg font-medium transition-colors",
        "disabled:cursor-not-allowed",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner className="size-4" /> : icon}
      {children}
    </button>
  );
}
