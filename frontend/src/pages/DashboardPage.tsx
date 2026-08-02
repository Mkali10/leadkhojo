import { Link, useNavigate } from "react-router-dom";
import { useScans } from "@/api/queries";
import type { ScanSummary } from "@/api/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { ScanStatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Loading } from "@/components/ui/Feedback";
import { formatDuration, formatRelative } from "@/lib/format";

function elapsed(scan: ScanSummary): number | null {
  if (!scan.started_at) return null;
  const end = scan.completed_at ? new Date(scan.completed_at) : new Date();
  return Math.max(0, Math.round((end.getTime() - new Date(scan.started_at).getTime()) / 1000));
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-4">
      <p className="label">{label}</p>
      <p className="tnum mt-1 text-2xl font-semibold text-ink-900">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

function ScanRow({ scan }: { scan: ScanSummary }) {
  const title = scan.keyword?.trim() || `${scan.provider} scan`;
  const seconds = elapsed(scan);

  return (
    <li>
      <Link
        to={`/scans/${scan.id}`}
        className="flex flex-col gap-2 px-4 py-3.5 transition-colors hover:bg-brand-50/40 sm:flex-row sm:items-center sm:gap-4"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium text-ink-900">{title}</span>
            <ScanStatusBadge status={scan.status} />
            {scan.rerun_of_id && (
              <span className="text-xs text-ink-400" title="This scan re-runs an earlier one">
                re-run
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-ink-500">
            {scan.location ? `${scan.location} · ` : ""}
            {formatRelative(scan.created_at)}
            {seconds !== null && ` · ${formatDuration(seconds)}`}
          </p>
        </div>

        <div className="tnum flex shrink-0 items-center gap-4 text-sm">
          <span className="text-ink-600">
            {scan.completed_count}
            <span className="text-ink-400">/{scan.total_businesses || "—"}</span>
          </span>
          {scan.failed_count > 0 && (
            <span className="text-high" title={`${scan.failed_count} could not be analysed`}>
              {scan.failed_count} failed
            </span>
          )}
        </div>
      </Link>
    </li>
  );
}

export function DashboardPage() {
  const navigate = useNavigate();
  const { data, isPending, error, refetch } = useScans(25, 0);

  const scans = data?.data ?? [];
  const running = scans.filter((s) => !["completed", "failed", "cancelled"].includes(s.status));
  const analysed = scans.reduce((sum, s) => sum + s.completed_count, 0);

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Every scan you have run on this instance."
        actions={
          <Button variant="primary" onClick={() => navigate("/scans/new")}>
            New scan
          </Button>
        }
      />

      {isPending ? (
        <Loading label="Loading scans…" />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : scans.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No scans yet"
            description="Give LeadKhojo a list of domains or a keyword. It will crawl each public website, work out what is wrong with it, and tell you what to pitch."
            action={
              <Button variant="primary" onClick={() => navigate("/scans/new")}>
                Run your first scan
              </Button>
            }
          />
        </div>
      ) : (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Scans" value={String(data?.pagination.total ?? scans.length)} />
            <StatCard label="Running" value={String(running.length)} hint={running.length ? "polling live" : undefined} />
            <StatCard label="Businesses analysed" value={String(analysed)} hint="in the last 25 scans" />
            <StatCard
              label="Latest"
              value={scans[0] ? formatRelative(scans[0].created_at) : "—"}
            />
          </div>

          <div className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-ink-200 px-4 py-2.5">
              <h2 className="text-sm font-semibold text-ink-800">Recent scans</h2>
              <Link to="/compare" className="text-xs font-medium text-brand-700 hover:underline">
                Compare two scans
              </Link>
            </div>
            <ul className="divide-y divide-ink-100">
              {scans.map((scan) => (
                <ScanRow key={scan.id} scan={scan} />
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
