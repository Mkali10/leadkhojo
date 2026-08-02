import { useSearchParams } from "react-router-dom";
import { useComparison, useScans } from "@/api/queries";
import { PageHeader } from "@/components/layout/PageHeader";
import { Select } from "@/components/ui/Field";
import { EmptyState, ErrorState, Loading } from "@/components/ui/Feedback";
import { ComparisonTable } from "@/components/compare/ComparisonTable";
import { formatRelative } from "@/lib/format";

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "good" | "critical" | "brand" | "muted";
}) {
  const colour =
    tone === "critical"
      ? "text-critical"
      : tone === "good"
        ? "text-good"
        : tone === "brand"
          ? "text-brand-600"
          : "text-ink-500";
  return (
    <div className="card p-4">
      <p className="label">{label}</p>
      <p className={`tnum mt-1 text-2xl font-semibold ${colour}`}>{value}</p>
    </div>
  );
}

export function ComparePage() {
  const [params, setParams] = useSearchParams();
  const base = params.get("base") ?? "";
  const compare = params.get("compare") ?? "";

  // Only terminal scans can be compared — diffing against a run that is still
  // writing rows produces a moving baseline.
  const { data: scanList, isPending: scansPending } = useScans(100, 0);
  const options = (scanList?.data ?? []).filter((scan) =>
    ["completed", "failed", "cancelled"].includes(scan.status),
  );

  const comparison = useComparison(base || undefined, compare || undefined);

  const setSide = (side: "base" | "compare", value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(side, value);
    else next.delete(side);
    setParams(next, { replace: true });
  };

  const toOption = (scanId: string) => {
    const scan = options.find((s) => s.id === scanId);
    if (!scan) return { value: scanId, label: scanId.slice(0, 8) };
    const title = scan.keyword?.trim() || `${scan.provider} scan`;
    return { value: scan.id, label: `${title} · ${formatRelative(scan.created_at)}` };
  };

  const selectOptions = [
    { value: "", label: "Choose a scan…" },
    ...options.map((scan) => toOption(scan.id)),
  ];

  return (
    <>
      <PageHeader
        title="Compare scans"
        subtitle="What changed between two runs of the same targets. This is what turns a one-off audit into a reason to call back."
        back={{ to: "/", label: "Dashboard" }}
      />

      <div className="card mb-6 flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
        <div className="flex-1">
          <p className="label mb-1.5">Earlier scan</p>
          <Select
            options={selectOptions}
            value={base}
            onChange={(event) => setSide("base", event.target.value)}
            className="w-full"
          />
        </div>
        <div className="pb-2 text-center text-ink-300" aria-hidden="true">
          →
        </div>
        <div className="flex-1">
          <p className="label mb-1.5">Later scan</p>
          <Select
            options={selectOptions}
            value={compare}
            onChange={(event) => setSide("compare", event.target.value)}
            className="w-full"
          />
        </div>
      </div>

      {scansPending ? (
        <Loading label="Loading scans…" />
      ) : options.length < 2 ? (
        <div className="card">
          <EmptyState
            title="Not enough finished scans yet"
            description="Comparison needs two completed scans. Re-run an existing scan to produce a second one against the same targets."
          />
        </div>
      ) : !base || !compare ? (
        <div className="card">
          <EmptyState
            title="Pick two scans"
            description="Choose an earlier and a later scan. Results are matched by domain, so the two do not have to contain exactly the same businesses."
          />
        </div>
      ) : base === compare ? (
        <div className="card">
          <EmptyState title="Those are the same scan" description="Choose two different runs." />
        </div>
      ) : comparison.isPending ? (
        <Loading label="Comparing…" />
      ) : comparison.error ? (
        <ErrorState error={comparison.error} onRetry={() => void comparison.refetch()} />
      ) : comparison.data ? (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
            <StatCard label="Compared" value={comparison.data.total_compared} />
            <StatCard label="Changed" value={comparison.data.changed} tone="critical" />
            <StatCard label="Unchanged" value={comparison.data.unchanged} tone="good" />
            <StatCard label="Added" value={comparison.data.added} tone="brand" />
            <StatCard label="Removed" value={comparison.data.removed} tone="muted" />
          </div>

          {comparison.data.businesses.length > 0 ? (
            <ComparisonTable businesses={comparison.data.businesses} />
          ) : (
            <div className="card">
              <EmptyState
                title="Nothing to compare"
                description="Neither scan produced a business with a domain to match on."
              />
            </div>
          )}
        </>
      ) : null}
    </>
  );
}
