import type { ReactNode } from "react";
import { classNames } from "@/lib/format";
import type { FindingStatus, ScanStatus, Severity, Urgency } from "@/api/types";

type Tone =
  | "neutral"
  | "brand"
  | "good"
  | "low"
  | "medium"
  | "high"
  | "critical"
  | "muted";

const TONES: Record<Tone, string> = {
  neutral: "bg-ink-100 text-ink-700 ring-ink-200",
  brand: "bg-brand-50 text-brand-700 ring-brand-200",
  good: "bg-good/10 text-good ring-good/25",
  low: "bg-low/10 text-low ring-low/25",
  medium: "bg-medium/10 text-medium ring-medium/25",
  high: "bg-high/10 text-high ring-high/25",
  critical: "bg-critical/10 text-critical ring-critical/25",
  muted: "bg-ink-50 text-ink-400 ring-ink-200",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={classNames(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const SEVERITY_TONE: Record<Severity, Tone> = {
  critical: "critical",
  high: "high",
  medium: "medium",
  low: "low",
  info: "neutral",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge tone={SEVERITY_TONE[severity]}>{severity}</Badge>;
}

const URGENCY_TONE: Record<Urgency, Tone> = {
  critical: "critical",
  high: "high",
  medium: "medium",
  low: "low",
};

export function UrgencyBadge({ urgency }: { urgency: Urgency }) {
  return <Badge tone={URGENCY_TONE[urgency]}>{urgency}</Badge>;
}

/**
 * `not_applicable` gets its own muted treatment and an explanatory tooltip.
 *
 * It is not a pass and not a problem: it means the check could not be
 * evaluated — a DNS lookup that never answered, a page that was never
 * fetched. Rendering it as either of the other two would put a claim on
 * screen that the data does not support.
 */
const FINDING_TONE: Record<FindingStatus, Tone> = {
  pass: "good",
  fail: "critical",
  warn: "high",
  info: "neutral",
  not_applicable: "muted",
};

const FINDING_LABEL: Record<FindingStatus, string> = {
  pass: "pass",
  fail: "fail",
  warn: "warn",
  info: "info",
  not_applicable: "not checked",
};

export function FindingStatusBadge({ status }: { status: FindingStatus }) {
  return (
    <Badge
      tone={FINDING_TONE[status]}
      title={
        status === "not_applicable"
          ? "This check could not be evaluated, so nothing is claimed either way."
          : undefined
      }
    >
      {FINDING_LABEL[status]}
    </Badge>
  );
}

const SCAN_TONE: Record<ScanStatus, Tone> = {
  pending: "neutral",
  discovering: "brand",
  analyzing: "brand",
  completed: "good",
  failed: "critical",
  cancelled: "muted",
};

export function ScanStatusBadge({ status }: { status: ScanStatus }) {
  const live = status === "analyzing" || status === "discovering" || status === "pending";
  return (
    <Badge tone={SCAN_TONE[status]}>
      {live && (
        <span className="relative flex size-1.5" aria-hidden="true">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex size-1.5 rounded-full bg-current" />
        </span>
      )}
      {status}
    </Badge>
  );
}
