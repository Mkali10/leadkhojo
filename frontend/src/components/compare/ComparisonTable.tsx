import type { BusinessComparison, ComparisonState, ScoreDelta } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { classNames } from "@/lib/format";

const STATE_TONE: Record<ComparisonState, "good" | "critical" | "brand" | "muted"> = {
  added: "brand",
  removed: "muted",
  changed: "critical",
  unchanged: "good",
};

const SCORE_KEYS = ["opportunity", "lead", "security", "website"] as const;

/**
 * A score delta.
 *
 * Both sides are shown, not just the arrow. "+18" alone cannot be
 * sanity-checked by the person reading it; "54 → 72" can.
 */
function Delta({ delta, invert = false }: { delta: ScoreDelta | undefined; invert?: boolean }) {
  if (!delta || delta.before === null || delta.after === null) {
    return <span className="text-xs text-ink-300">—</span>;
  }
  const change = delta.change ?? 0;
  if (change === 0) {
    return <span className="tnum text-xs text-ink-400">{delta.after}</span>;
  }

  // For health scores up is good; for opportunity a rise means more to sell,
  // which is good news for the user but bad news about the site.
  const positive = invert ? change < 0 : change > 0;

  return (
    <span className="tnum inline-flex items-baseline gap-1 text-xs whitespace-nowrap">
      <span className="text-ink-400">{delta.before}</span>
      <span aria-hidden="true" className="text-ink-300">→</span>
      <span className={classNames("font-semibold", positive ? "text-good" : "text-critical")}>
        {delta.after}
      </span>
      <span className={classNames("text-[11px]", positive ? "text-good" : "text-critical")}>
        ({change > 0 ? "+" : ""}
        {change})
      </span>
    </span>
  );
}

function RuleChips({
  items,
  tone,
  label,
}: {
  items: string[];
  tone: "critical" | "good";
  label: string;
}) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-[11px] text-ink-500">{label}</span>
      {items.map((item) => (
        <Badge key={item} tone={tone}>
          {item}
        </Badge>
      ))}
    </div>
  );
}

export function ComparisonTable({ businesses }: { businesses: BusinessComparison[] }) {
  // Changed first: it is the only group that gives anyone a reason to act.
  const order: Record<ComparisonState, number> = {
    changed: 0,
    added: 1,
    removed: 2,
    unchanged: 3,
  };
  const sorted = [...businesses].sort(
    (a, b) => order[a.state] - order[b.state] || a.domain.localeCompare(b.domain),
  );

  return (
    <div className="scroll-x card">
      <table className="w-full min-w-[52rem] text-left text-sm">
        <thead className="border-b border-ink-200 bg-ink-50/60">
          <tr className="label">
            <th scope="col" className="px-4 py-2.5 font-medium">Business</th>
            <th scope="col" className="px-4 py-2.5 font-medium">State</th>
            {SCORE_KEYS.map((key) => (
              <th key={key} scope="col" className="px-4 py-2.5 font-medium">
                {key}
              </th>
            ))}
            <th scope="col" className="px-4 py-2.5 font-medium">What changed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-100">
          {sorted.map((row) => (
            <tr key={row.domain} className={classNames(row.state === "unchanged" && "opacity-60")}>
              <td className="max-w-[16rem] px-4 py-3">
                <p className="truncate font-medium text-ink-900">{row.name}</p>
                <p className="truncate text-xs text-ink-500">{row.domain}</p>
              </td>
              <td className="px-4 py-3">
                <Badge tone={STATE_TONE[row.state]}>{row.state}</Badge>
              </td>
              {SCORE_KEYS.map((key) => (
                <td key={key} className="px-4 py-3">
                  <Delta delta={row.scores[key]} invert={key === "opportunity"} />
                </td>
              ))}
              <td className="px-4 py-3">
                <div className="space-y-1">
                  <RuleChips items={row.opportunities_gained} tone="critical" label="new:" />
                  <RuleChips items={row.opportunities_resolved} tone="good" label="fixed:" />
                  <RuleChips items={row.technologies_added} tone="critical" label="tech +" />
                  <RuleChips items={row.technologies_removed} tone="good" label="tech −" />
                  {row.state === "unchanged" && (
                    <span className="text-xs text-ink-400">nothing</span>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
