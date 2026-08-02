import { useMemo, useState } from "react";
import type { FindingDetail } from "@/api/types";
import { FindingStatusBadge, SeverityBadge } from "@/components/ui/Badge";
import { EvidenceTable } from "@/components/ui/Evidence";
import { SEVERITY_ORDER, classNames } from "@/lib/format";

type Group = "problems" | "passing" | "unchecked";

const GROUP_LABEL: Record<Group, string> = {
  problems: "Problems",
  passing: "Passing",
  unchecked: "Not checked",
};

const GROUP_HINT: Record<Group, string> = {
  problems: "Findings you can act on. Each one carries the evidence behind it.",
  passing: "Checks this site already satisfies.",
  // The distinction that stops a false accusation reaching a prospect.
  unchecked:
    "These could not be evaluated — a lookup that never answered, or a page that was never fetched. Nothing is claimed either way.",
};

function groupOf(finding: FindingDetail): Group {
  if (finding.status === "fail" || finding.status === "warn") return "problems";
  if (finding.status === "not_applicable") return "unchecked";
  return "passing";
}

function FindingCard({ finding }: { finding: FindingDetail }) {
  const [open, setOpen] = useState(false);
  const isProblem = finding.status === "fail" || finding.status === "warn";

  return (
    <li
      className={classNames(
        "rounded-lg border px-4 py-3",
        isProblem ? "border-ink-200 bg-white" : "border-ink-100 bg-ink-50/40",
      )}
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5">
        <div className="min-w-0 flex-1">
          <p
            className={classNames(
              "text-sm font-medium",
              isProblem ? "text-ink-900" : "text-ink-600",
            )}
          >
            {finding.title}
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-ink-400">
            {finding.check_id} · {finding.category}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {isProblem && <SeverityBadge severity={finding.severity} />}
          <FindingStatusBadge status={finding.status} />
        </div>
      </div>

      {finding.description && (
        <p className="mt-2 text-sm text-ink-600">{finding.description}</p>
      )}

      {(Object.keys(finding.evidence).length > 0 || finding.remediation) && (
        <>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline"
          >
            <svg
              viewBox="0 0 24 24"
              className={classNames("size-3.5 transition-transform", open && "rotate-90")}
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              aria-hidden="true"
            >
              <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {open ? "Hide evidence" : "Show evidence"}
          </button>

          {open && (
            <div className="mt-2 space-y-3 border-t border-ink-100 pt-3">
              <EvidenceTable evidence={finding.evidence} />
              {finding.remediation && (
                <div>
                  <p className="label mb-1">How to fix it</p>
                  <p className="text-xs text-ink-600">{finding.remediation}</p>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </li>
  );
}

export function FindingList({ findings }: { findings: FindingDetail[] }) {
  const grouped = useMemo(() => {
    const buckets: Record<Group, FindingDetail[]> = {
      problems: [],
      passing: [],
      unchecked: [],
    };
    for (const finding of findings) buckets[groupOf(finding)].push(finding);
    buckets.problems.sort(
      (a, b) =>
        SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
        a.check_id.localeCompare(b.check_id),
    );
    for (const key of ["passing", "unchecked"] as const) {
      buckets[key].sort((a, b) => a.check_id.localeCompare(b.check_id));
    }
    return buckets;
  }, [findings]);

  return (
    <div className="space-y-6">
      {(["problems", "passing", "unchecked"] as Group[]).map((group) => {
        const items = grouped[group];
        if (items.length === 0) return null;
        return (
          <section key={group}>
            <h3 className="text-sm font-semibold text-ink-800">
              {GROUP_LABEL[group]}{" "}
              <span className="tnum font-normal text-ink-400">({items.length})</span>
            </h3>
            <p className="mt-0.5 mb-2 text-xs text-ink-500">{GROUP_HINT[group]}</p>
            <ul className="space-y-2">
              {items.map((finding) => (
                <FindingCard key={finding.check_id} finding={finding} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
