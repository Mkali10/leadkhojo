import type { ScanProgress } from "@/api/types";
import { isTerminal } from "@/api/types";
import { classNames, formatDuration } from "@/lib/format";
import { Spinner } from "@/components/ui/Spinner";

const BAR_TONE: Record<string, string> = {
  completed: "bg-good",
  failed: "bg-critical",
  cancelled: "bg-ink-300",
  running: "bg-brand-500",
};

/**
 * Live progress.
 *
 * The name of the site being analysed is the important part. A bare
 * percentage tells the user to wait; a name tells them the thing is alive and
 * roughly how far through it is. The backend returns `current_business`
 * specifically so this can be shown.
 */
export function ProgressPanel({ progress }: { progress: ScanProgress }) {
  const done = isTerminal(progress.status);
  const tone = done ? BAR_TONE[progress.status] ?? "bg-ink-300" : BAR_TONE.running;
  const remaining = Math.max(
    0,
    progress.total_businesses - progress.completed_count - progress.failed_count,
  );

  return (
    <section className="card p-5" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="flex items-center gap-2">
          {!done && <Spinner className="size-4 text-brand-600" />}
          <h2 className="text-sm font-semibold text-ink-800">
            {done ? "Scan finished" : "Scanning"}
          </h2>
        </div>
        <span className="tnum text-sm text-ink-500">
          {progress.completed_count + progress.failed_count} of {progress.total_businesses || "—"}
          {progress.elapsed_seconds !== null && ` · ${formatDuration(progress.elapsed_seconds)}`}
        </span>
      </div>

      <div
        className="mt-3 h-2 w-full overflow-hidden rounded-full bg-ink-100"
        role="progressbar"
        aria-valuenow={progress.percent_complete}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Scan progress"
      >
        <div
          className={classNames("h-full rounded-full transition-[width] duration-500", tone)}
          style={{ width: `${progress.percent_complete}%` }}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
        <span className="tnum font-semibold text-ink-900">{progress.percent_complete}%</span>
        <span className="text-ink-500">
          <span className="tnum font-medium text-good">{progress.completed_count}</span> analysed
        </span>
        {progress.failed_count > 0 && (
          <span className="text-ink-500">
            <span className="tnum font-medium text-high">{progress.failed_count}</span> failed
          </span>
        )}
        {!done && remaining > 0 && (
          <span className="tnum text-ink-400">{remaining} queued</span>
        )}
      </div>

      {!done && progress.current_business && (
        <p className="mt-3 truncate text-sm text-ink-600">
          Now analysing <span className="font-medium text-ink-900">{progress.current_business}</span>
        </p>
      )}

      {progress.error_message && (
        <p className="mt-3 rounded-lg bg-critical/5 px-3 py-2 text-sm text-critical">
          {progress.error_message}
        </p>
      )}

      {progress.failed_count > 0 && done && (
        <p className="mt-3 text-xs text-ink-500">
          A failed site means the crawl could not complete — a timeout, a refused connection or
          a page we were not allowed to fetch. It is recorded rather than hidden, and nothing is
          claimed about a site we could not read.
        </p>
      )}
    </section>
  );
}
