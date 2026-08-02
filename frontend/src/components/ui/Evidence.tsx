import { formatEvidenceValue, humanize } from "@/lib/format";

/**
 * Evidence is the whole promise of the product.
 *
 * Every failing finding carries the record, header value or date that proves
 * it, and the user is going to repeat that claim to a stranger. So it is
 * shown verbatim — selectable, monospaced, never summarised — because the
 * only thing worse than a missing claim is one they cannot back up.
 */
export function EvidenceTable({ evidence }: { evidence: Record<string, unknown> }) {
  const entries = Object.entries(evidence).filter(([key]) => !key.startsWith("_"));

  if (entries.length === 0) {
    return (
      <p className="text-xs text-ink-500 italic">
        No structured evidence recorded for this item.
      </p>
    );
  }

  return (
    <dl className="grid gap-x-4 gap-y-1.5 text-xs sm:grid-cols-[minmax(7rem,auto)_1fr]">
      {entries.map(([key, value]) => {
        const rendered = formatEvidenceValue(value);
        const multiline = rendered.includes("\n");
        return (
          <div key={key} className="contents">
            <dt className="text-ink-500">{humanize(key)}</dt>
            <dd className="min-w-0">
              {multiline ? (
                <pre className="scroll-x max-h-40 rounded bg-ink-50 p-2 font-mono text-[11px] break-words whitespace-pre-wrap text-ink-800">
                  {rendered}
                </pre>
              ) : (
                <span className="font-mono break-all text-ink-800 select-all">{rendered}</span>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
