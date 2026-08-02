import type { Severity, Urgency } from "@/api/types";

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";

  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";

  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["minute", 60],
    ["hour", 3600],
    ["day", 86400],
    ["month", 2_592_000],
    ["year", 31_536_000],
  ];

  let chosen: Intl.RelativeTimeFormatUnit = "minute";
  let size = 60;
  for (const [unit, unitSeconds] of units) {
    if (seconds >= unitSeconds) {
      chosen = unit;
      size = unitSeconds;
    }
  }

  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  return formatter.format(-Math.round(seconds / size), chosen);
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "—";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function formatMillis(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** Turn `snake_case_key` into readable text for evidence tables. */
export function humanize(key: string): string {
  const spaced = key.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Evidence values are arbitrary JSON. Render scalars plainly and only fall
 *  back to JSON for the shapes that need it. */
export function formatEvidenceValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) {
    return value.length ? value.map((v) => formatEvidenceValue(v)).join(", ") : "—";
  }
  return JSON.stringify(value, null, 2);
}

export const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

export const URGENCY_ORDER: Record<Urgency, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

export function scoreTone(score: number | null): "good" | "medium" | "high" | "critical" | "none" {
  if (score === null) return "none";
  if (score >= 75) return "good";
  if (score >= 50) return "medium";
  if (score >= 25) return "high";
  return "critical";
}

/** Opportunity score is the one where high means "worth calling", so its
 *  colour scale is deliberately the inverse of the health scores. */
export function opportunityTone(score: number | null): "good" | "medium" | "high" | "critical" | "none" {
  if (score === null) return "none";
  if (score >= 70) return "critical";
  if (score >= 45) return "high";
  if (score >= 20) return "medium";
  return "good";
}

export function classNames(...values: (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}
