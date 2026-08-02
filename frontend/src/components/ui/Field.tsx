import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { useId } from "react";
import { classNames } from "@/lib/format";

const CONTROL =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 " +
  "placeholder:text-ink-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 " +
  "focus:outline-none disabled:bg-ink-50 disabled:text-ink-400";

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-sm font-medium text-ink-800">
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1.5 text-xs text-critical">{error}</p>
      ) : hint ? (
        <p className="mt-1.5 text-xs text-ink-500">{hint}</p>
      ) : null}
    </div>
  );
}

interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: ReactNode;
  error?: string | null;
}

export function TextInput({ label, hint, error, className, ...rest }: TextInputProps) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} htmlFor={id}>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        className={classNames(CONTROL, error && "border-critical", className)}
        {...rest}
      />
    </Field>
  );
}

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hint?: ReactNode;
  error?: string | null;
}

export function TextArea({ label, hint, error, className, ...rest }: TextAreaProps) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} htmlFor={id}>
      <textarea
        id={id}
        aria-invalid={error ? true : undefined}
        className={classNames(CONTROL, "font-mono text-[13px]", error && "border-critical", className)}
        {...rest}
      />
    </Field>
  );
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: { value: string; label: string }[];
}

export function Select({ label, options, className, ...rest }: SelectProps) {
  return (
    <label className="inline-flex items-center gap-2 text-sm">
      {label && <span className="text-ink-500 whitespace-nowrap">{label}</span>}
      <select
        className={classNames(
          "rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-sm text-ink-900",
          "focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none",
          className,
        )}
        {...rest}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
