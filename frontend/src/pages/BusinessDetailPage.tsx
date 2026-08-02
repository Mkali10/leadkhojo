import { useState } from "react";
import { useParams } from "react-router-dom";
import { useBusiness } from "@/api/queries";
import { api } from "@/api/endpoints";
import type { ScoreKey } from "@/api/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState, Loading } from "@/components/ui/Feedback";
import { ScoreBar } from "@/components/ui/Score";
import { ContactList } from "@/components/business/ContactList";
import { FindingList } from "@/components/business/FindingList";
import { OpportunityList } from "@/components/business/OpportunityList";
import { TechnologyList } from "@/components/business/TechnologyList";
import { classNames, formatDateTime, formatMillis, humanize } from "@/lib/format";

type Tab = "opportunities" | "findings" | "contacts" | "technology";

const TABS: { id: Tab; label: string }[] = [
  { id: "opportunities", label: "Opportunities" },
  { id: "findings", label: "Findings" },
  { id: "contacts", label: "Contacts" },
  { id: "technology", label: "Technology" },
];

const SCORE_LABELS: Record<ScoreKey, string> = {
  opportunity: "Opportunity",
  lead: "Lead",
  security: "Security",
  website: "Website",
};

export function BusinessDetailPage() {
  const { businessId } = useParams<{ businessId: string }>();
  const [tab, setTab] = useState<Tab>("opportunities");
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<unknown>(null);

  const { data: business, isPending, error, refetch } = useBusiness(businessId);

  if (isPending) return <Loading label="Loading business…" />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!business) return null;

  const problems = business.findings.filter((f) => f.status === "fail" || f.status === "warn");
  const unchecked = business.findings.filter((f) => f.status === "not_applicable");

  const counts: Record<Tab, number> = {
    opportunities: business.opportunities.length,
    findings: problems.length,
    contacts: business.contacts.length,
    technology: business.technologies.length,
  };

  const download = async () => {
    setDownloading(true);
    setDownloadError(null);
    try {
      await api.downloadBusinessPdf(business.id, business.domain);
    } catch (err) {
      setDownloadError(err);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <>
      <PageHeader
        back={{ to: `/scans/${business.scan_id}`, label: "Back to results" }}
        title={business.name}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {business.website_url ? (
              <a
                href={business.website_url}
                target="_blank"
                rel="noreferrer noopener"
                className="text-brand-700 hover:underline"
              >
                {business.domain ?? business.website_url}
              </a>
            ) : (
              <span>{business.domain ?? "no website"}</span>
            )}
            {business.city && <span>· {business.city}</span>}
            {business.analyzed_at && <span>· analysed {formatDateTime(business.analyzed_at)}</span>}
          </span>
        }
        actions={
          <Button size="sm" loading={downloading} onClick={() => void download()}>
            Download report
          </Button>
        }
      />

      {downloadError && (
        <div className="mb-4">
          <ErrorState error={downloadError} />
        </div>
      )}

      {/* A failed crawl says so plainly, above everything else. Whatever is
          shown below came from DNS, which is collected separately — it is not
          evidence about a page nobody read. */}
      {business.status !== "completed" && (
        <div className="mb-6 rounded-lg border border-high/30 bg-high/5 px-4 py-3">
          <p className="text-sm font-medium text-high">
            {business.status === "no_website"
              ? "No website to analyse"
              : `The crawl did not complete — ${business.failure_reason ?? "unknown reason"}`}
          </p>
          {business.failure_detail && (
            <p className="mt-1 text-xs text-ink-600">{business.failure_detail}</p>
          )}
          <p className="mt-1 text-xs text-ink-500">
            Anything below comes from public DNS, which is looked up independently of the page
            fetch. Nothing is claimed about content that was never retrieved.
          </p>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="order-2 lg:order-1">
          <div
            role="tablist"
            aria-label="Analysis detail"
            className="mb-4 flex gap-1 overflow-x-auto border-b border-ink-200"
          >
            {TABS.map((entry) => (
              <button
                key={entry.id}
                role="tab"
                type="button"
                id={`tab-${entry.id}`}
                aria-selected={tab === entry.id}
                aria-controls="detail-panel"
                onClick={() => setTab(entry.id)}
                className={classNames(
                  "-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                  tab === entry.id
                    ? "border-brand-600 text-brand-700"
                    : "border-transparent text-ink-500 hover:text-ink-800",
                )}
              >
                {entry.label}
                <span className="tnum ml-1.5 text-xs text-ink-400">{counts[entry.id]}</span>
              </button>
            ))}
          </div>

          <div id="detail-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
            {tab === "opportunities" && <OpportunityList opportunities={business.opportunities} />}
            {tab === "findings" && (
              <>
                <FindingList findings={business.findings} />
                {unchecked.length > 0 && problems.length === 0 && (
                  <p className="mt-4 text-xs text-ink-500">
                    {unchecked.length} checks could not be evaluated on this site.
                  </p>
                )}
              </>
            )}
            {tab === "contacts" && (
              <div className="card p-4">
                <ContactList contacts={business.contacts} />
              </div>
            )}
            {tab === "technology" && (
              <div className="card p-4">
                <TechnologyList technologies={business.technologies} />
              </div>
            )}
          </div>
        </div>

        <aside className="order-1 space-y-4 lg:order-2">
          <div className="card p-4">
            <h2 className="mb-3 text-sm font-semibold text-ink-800">Scores</h2>
            {business.scores ? (
              <div className="space-y-3">
                {(["opportunity", "lead", "security", "website"] as ScoreKey[]).map((key) => (
                  <ScoreBar
                    key={key}
                    kind={key}
                    label={SCORE_LABELS[key]}
                    score={business.scores?.[key]?.total ?? null}
                  />
                ))}
              </div>
            ) : (
              <p className="text-sm text-ink-500">Not scored — the analysis did not complete.</p>
            )}
          </div>

          {business.scores?.opportunity?.components &&
            Object.keys(business.scores.opportunity.components).length > 0 && (
              <div className="card p-4">
                <h2 className="mb-2 text-sm font-semibold text-ink-800">
                  Why the opportunity score
                </h2>
                <dl className="space-y-1 text-xs">
                  {Object.entries(business.scores.opportunity.components).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-3">
                      <dt className="text-ink-500">{humanize(key)}</dt>
                      <dd className="tnum font-medium text-ink-800">{value}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-2 text-[11px] text-ink-400">
                  A score you cannot explain is a score you cannot act on.
                </p>
              </div>
            )}

          <div className="card p-4">
            <h2 className="mb-2 text-sm font-semibold text-ink-800">Primary contact</h2>
            {business.primary_email || business.primary_phone ? (
              <div className="space-y-1 text-sm">
                {business.primary_email && (
                  <a
                    href={`mailto:${business.primary_email}`}
                    className="block break-all text-brand-700 hover:underline"
                  >
                    {business.primary_email}
                  </a>
                )}
                {business.primary_phone && (
                  <span className="block text-ink-700">{business.primary_phone}</span>
                )}
              </div>
            ) : (
              <p className="text-sm text-ink-500">
                None published.{" "}
                <span className="text-ink-400">Never guessed from a pattern.</span>
              </p>
            )}
          </div>

          {business.snapshot && (
            <div className="card p-4">
              <h2 className="mb-2 text-sm font-semibold text-ink-800">Crawl</h2>
              <dl className="space-y-1 text-xs">
                {[
                  ["Pages read", String(business.snapshot.page_count)],
                  ["Took", formatMillis(business.snapshot.duration_ms)],
                  ["Mode", business.snapshot.render_mode],
                  ["Captured", formatDateTime(business.snapshot.captured_at)],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3">
                    <dt className="text-ink-500">{label}</dt>
                    <dd className="text-ink-800">{value}</dd>
                  </div>
                ))}
              </dl>
              {business.final_url && business.final_url !== business.website_url && (
                <p className="mt-2 truncate text-[11px] text-ink-400" title={business.final_url}>
                  redirected to {business.final_url}
                </p>
              )}
              <div className="mt-2">
                <Badge tone="neutral">{business.snapshot.status}</Badge>
              </div>
            </div>
          )}
        </aside>
      </div>
    </>
  );
}
