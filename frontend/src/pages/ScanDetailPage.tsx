import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  keys,
  useBusinesses,
  useCancelScan,
  useDeleteScan,
  useRerunScan,
  useScan,
  useScanProgress,
} from "@/api/queries";
import { api } from "@/api/endpoints";
import { isTerminal } from "@/api/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { ScanStatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Loading } from "@/components/ui/Feedback";
import { ProgressPanel } from "@/components/scan/ProgressPanel";
import { ResultFilters } from "@/components/results/ResultFilters";
import { DEFAULT_FILTERS, type FilterState } from "@/components/results/filters";
import { Pager } from "@/components/results/Pager";
import { ResultsTable } from "@/components/results/ResultsTable";
import { formatDateTime } from "@/lib/format";

export function ScanDetailPage() {
  const { scanId } = useParams<{ scanId: string }>();
  const navigate = useNavigate();

  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const [busy, setBusy] = useState<"csv" | "pdf" | null>(null);

  const queryClient = useQueryClient();
  const scanQuery = useScan(scanId);
  const progressQuery = useScanProgress(scanId);
  const progress = progressQuery.data;
  const live = progress ? !isTerminal(progress.status) : false;

  const businessesQuery = useBusinesses(scanId, filters, { live });

  /**
   * Progress is the only thing polling, so the scan summary goes stale the
   * moment a run finishes: the header would keep saying "pending" and keep
   * offering Cancel while the panel below it said "Scan finished".
   *
   * Refetching the summary once, on the transition to terminal, brings
   * completed_at and the final counts back in step without a second poller.
   */
  const terminal = progress ? isTerminal(progress.status) : false;
  useEffect(() => {
    if (!scanId || !terminal) return;
    void queryClient.invalidateQueries({ queryKey: keys.scan(scanId) });
    void queryClient.invalidateQueries({ queryKey: keys.scans });
  }, [scanId, terminal, queryClient]);

  const rerun = useRerunScan();
  const cancel = useCancelScan();
  const remove = useDeleteScan();

  const scan = scanQuery.data;

  const runDownload = async (kind: "csv" | "pdf") => {
    if (!scanId) return;
    setBusy(kind);
    setDownloadError(null);
    try {
      await (kind === "csv" ? api.downloadScanCsv(scanId) : api.downloadScanPdf(scanId));
    } catch (error) {
      setDownloadError(error);
    } finally {
      setBusy(null);
    }
  };

  if (scanQuery.isPending) return <Loading label="Loading scan…" />;
  if (scanQuery.error) return <ErrorState error={scanQuery.error} onRetry={() => void scanQuery.refetch()} />;
  if (!scan) return null;

  const title = scan.keyword?.trim() || `${scan.provider} scan`;
  // Progress is the live source; the summary is a snapshot that can lag it by
  // a poll. Prefer progress wherever the two describe the same thing, so the
  // header and the panel below it can never contradict each other.
  const status = progress?.status ?? scan.status;
  const finished = isTerminal(status);
  const hasResults = (businessesQuery.data?.pagination.total ?? 0) > 0;

  return (
    <>
      <PageHeader
        back={{ to: "/", label: "Dashboard" }}
        title={title}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <ScanStatusBadge status={status} />
            <span>Started {formatDateTime(scan.started_at ?? scan.created_at)}</span>
            {scan.location && <span>· {scan.location}</span>}
            {scan.rerun_of_id && (
              <button
                type="button"
                onClick={() => navigate(`/compare?base=${scan.rerun_of_id}&compare=${scan.id}`)}
                className="text-brand-700 hover:underline"
              >
                compare with the original
              </button>
            )}
          </span>
        }
        actions={
          <>
            <Button
              size="sm"
              onClick={() => void runDownload("csv")}
              loading={busy === "csv"}
              disabled={!hasResults}
            >
              CSV
            </Button>
            <Button
              size="sm"
              onClick={() => void runDownload("pdf")}
              loading={busy === "pdf"}
              disabled={!hasResults}
            >
              PDF
            </Button>

            {finished ? (
              <Button
                size="sm"
                loading={rerun.isPending}
                onClick={async () => {
                  const next = await rerun.mutateAsync(scan.id);
                  navigate(`/scans/${next.id}`);
                }}
                title="Runs the same targets again as a new scan, so the two can be compared"
              >
                Re-run
              </Button>
            ) : (
              <Button size="sm" loading={cancel.isPending} onClick={() => cancel.mutate(scan.id)}>
                Cancel
              </Button>
            )}

            <Button
              size="sm"
              variant="danger"
              loading={remove.isPending}
              onClick={async () => {
                if (!window.confirm("Delete this scan and all of its results? This cannot be undone.")) return;
                await remove.mutateAsync(scan.id);
                navigate("/");
              }}
            >
              Delete
            </Button>
          </>
        }
      />

      {progress && (
        <div className="mb-6">
          <ProgressPanel progress={progress} />
        </div>
      )}

      {rerun.error && <div className="mb-4"><ErrorState error={rerun.error} /></div>}
      {cancel.error && <div className="mb-4"><ErrorState error={cancel.error} /></div>}
      {downloadError && (
        <div className="mb-4">
          <ErrorState error={downloadError} />
        </div>
      )}

      <section>
        <ResultFilters
          filters={filters}
          onChange={setFilters}
          total={businessesQuery.data?.pagination.total ?? 0}
        />

        {businessesQuery.isPending ? (
          <Loading label="Loading results…" />
        ) : businessesQuery.error ? (
          <ErrorState error={businessesQuery.error} onRetry={() => void businessesQuery.refetch()} />
        ) : businessesQuery.data && businessesQuery.data.data.length > 0 ? (
          <>
            <ResultsTable rows={businessesQuery.data.data} />
            <Pager
              pagination={businessesQuery.data.pagination}
              onOffset={(offset) => setFilters({ ...filters, offset })}
            />
          </>
        ) : (
          <div className="card">
            <EmptyState
              title={live ? "No results yet" : "Nothing matches these filters"}
              description={
                live
                  ? "Rows appear here as each site finishes, so this will fill in while the scan runs."
                  : "Try widening the status filter — failed sites and businesses without a website are hidden by default."
              }
            />
          </div>
        )}
      </section>
    </>
  );
}
