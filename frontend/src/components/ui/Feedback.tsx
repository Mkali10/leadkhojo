import type { ReactNode } from "react";
import { ApiError } from "@/api/client";
import { classNames } from "@/lib/format";
import { Button } from "./Button";
import { Spinner } from "./Spinner";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 px-6 py-16 text-ink-500">
      <Spinner />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={classNames("animate-pulse rounded bg-ink-100", className)} />;
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      {icon && <div className="mb-3 text-ink-300">{icon}</div>}
      <h3 className="text-base font-semibold text-ink-800">{title}</h3>
      {description && (
        <p className="mt-1 max-w-md text-sm text-ink-500">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/**
 * Show the server's own explanation.
 *
 * Every error path returns RFC 9457 Problem Details with a human-readable
 * `detail` and a correlation id. Replacing that with "Something went wrong"
 * throws away the only two things that help someone fix it.
 */
export function ErrorState({
  error,
  onRetry,
  compact = false,
}: {
  error: unknown;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const api = error instanceof ApiError ? error : null;
  const message =
    api?.detail ?? (error instanceof Error ? error.message : "The request failed.");

  return (
    <div
      role="alert"
      className={classNames(
        "rounded-lg border border-critical/25 bg-critical/5 text-sm text-ink-800",
        compact ? "px-3 py-2" : "px-4 py-4",
      )}
    >
      <p className="font-medium text-critical">
        {api?.status ? `${api.status} · ${api.code}` : "Request failed"}
      </p>
      <p className="mt-1 text-ink-700">{message}</p>

      {api?.fieldErrors.length ? (
        <ul className="mt-2 space-y-0.5 text-ink-600">
          {api.fieldErrors.map((fieldError) => (
            <li key={fieldError.field}>
              <code className="text-xs">{fieldError.field}</code> — {fieldError.message}
            </li>
          ))}
        </ul>
      ) : null}

      {api?.correlationId && (
        <p className="mt-2 text-xs text-ink-500">
          Correlation id <code className="select-all">{api.correlationId}</code> — quote this
          when reporting it.
        </p>
      )}

      {onRetry && (
        <div className="mt-3">
          <Button size="sm" onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}
    </div>
  );
}
