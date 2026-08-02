import { classNames, opportunityTone, scoreTone } from "@/lib/format";
import type { ScoreKey } from "@/api/types";

const TONE_BAR: Record<string, string> = {
  good: "bg-good",
  medium: "bg-medium",
  high: "bg-high",
  critical: "bg-critical",
  none: "bg-ink-200",
};

const TONE_TEXT: Record<string, string> = {
  good: "text-good",
  medium: "text-medium",
  high: "text-high",
  critical: "text-critical",
  none: "text-ink-400",
};

/** Opportunity is "how much is there to sell", so a high number is good news
 *  for the user. Health scores are the opposite. They cannot share a scale. */
function toneFor(kind: ScoreKey, score: number | null): string {
  return kind === "opportunity" ? opportunityTone(score) : scoreTone(score);
}

export function ScorePill({
  kind,
  score,
  className,
}: {
  kind: ScoreKey;
  score: number | null;
  className?: string;
}) {
  const tone = toneFor(kind, score);
  return (
    <span
      className={classNames("tnum text-sm font-semibold", TONE_TEXT[tone], className)}
      title={score === null ? "Not scored" : `${kind} score ${score} of 100`}
    >
      {score ?? "—"}
    </span>
  );
}

export function ScoreBar({
  kind,
  label,
  score,
}: {
  kind: ScoreKey;
  label: string;
  score: number | null;
}) {
  const tone = toneFor(kind, score);
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-ink-600">{label}</span>
        <span className={classNames("tnum text-sm font-semibold", TONE_TEXT[tone])}>
          {score ?? "—"}
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-ink-100"
        role="progressbar"
        aria-valuenow={score ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label} score`}
      >
        <div
          className={classNames("h-full rounded-full transition-[width]", TONE_BAR[tone])}
          style={{ width: `${score ?? 0}%` }}
        />
      </div>
    </div>
  );
}
