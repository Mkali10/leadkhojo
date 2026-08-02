import { useState } from "react";
import type { OpportunityDetail } from "@/api/types";
import { Badge, UrgencyBadge } from "@/components/ui/Badge";
import { EvidenceTable } from "@/components/ui/Evidence";
import { EmptyState } from "@/components/ui/Feedback";
import { URGENCY_ORDER, classNames } from "@/lib/format";

function OpportunityCard({ opportunity }: { opportunity: OpportunityDetail }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(opportunity.description);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <li className="card p-4">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-semibold text-ink-900">{opportunity.title}</h4>
          <p className="mt-0.5 font-mono text-[11px] text-ink-400">
            {opportunity.rule_id} · {opportunity.category}
          </p>
        </div>
        <UrgencyBadge urgency={opportunity.urgency} />
      </div>

      {/* The deterministic text produced by the rule engine. This is the
          version to put in front of a prospect, so it is the one shown. */}
      <p className="mt-3 text-sm leading-relaxed text-ink-700">{opportunity.description}</p>

      {/* A rewrite never replaces the sentence above; both are returned, and
          the defensible one stays visible. v1 ships no rewriter, so this is
          normally absent. */}
      {opportunity.description_ai && (
        <div className="mt-3 rounded-lg border border-brand-200 bg-brand-50/60 px-3 py-2">
          <p className="label mb-1 text-brand-700">AI rewrite</p>
          <p className="text-sm text-ink-700">{opportunity.description_ai}</p>
          <p className="mt-1.5 text-[11px] text-ink-500">
            Rephrased from the text above. The original remains the source of truth.
          </p>
        </div>
      )}

      <div className="mt-3 rounded-lg bg-ink-50 px-3 py-2">
        <p className="label mb-1">How to pitch it</p>
        <p className="text-sm text-ink-600">{opportunity.pitch_angle}</p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={copy}
          className="text-xs font-medium text-brand-700 hover:underline"
        >
          {copied ? "Copied" : "Copy the wording"}
        </button>
        <span className="text-ink-300" aria-hidden="true">·</span>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="text-xs font-medium text-brand-700 hover:underline"
        >
          {open ? "Hide evidence" : "Show evidence"}
        </button>
        {opportunity.triggered_by.length > 0 && (
          <div className="ml-auto flex flex-wrap gap-1">
            {opportunity.triggered_by.map((checkId) => (
              <Badge key={checkId} tone="neutral" title="The finding this came from">
                {checkId}
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className={classNames("mt-3 border-t border-ink-100 pt-3", !open && "hidden")}>
        <EvidenceTable evidence={opportunity.evidence} />
      </div>
    </li>
  );
}

export function OpportunityList({ opportunities }: { opportunities: OpportunityDetail[] }) {
  if (opportunities.length === 0) {
    return (
      <EmptyState
        title="No opportunities found"
        description="Nothing here is a defect. The rules only fire when there is a specific, evidenced problem to sell against — a clean site produces nothing, and that is the correct answer."
      />
    );
  }

  const sorted = [...opportunities].sort(
    (a, b) => URGENCY_ORDER[a.urgency] - URGENCY_ORDER[b.urgency] || a.rule_id.localeCompare(b.rule_id),
  );

  return <ul className="space-y-3">{sorted.map((o) => <OpportunityCard key={o.rule_id} opportunity={o} />)}</ul>;
}
