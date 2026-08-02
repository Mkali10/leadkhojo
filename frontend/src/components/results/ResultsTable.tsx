import { Link } from "react-router-dom";
import type { BusinessRow } from "@/api/types";
import { Badge, UrgencyBadge } from "@/components/ui/Badge";
import { ScorePill } from "@/components/ui/Score";
import { classNames } from "@/lib/format";

/** Missing contact is a real, correct answer — the extractor never guesses an
 *  address. It reads as an explicit statement, not an empty cell. */
function ContactCell({ row }: { row: BusinessRow }) {
  if (!row.primary_email && !row.primary_phone) {
    return (
      <span
        className="text-xs text-ink-400 italic"
        title="No contact details are published on this website. Addresses are never guessed or constructed."
      >
        none published
      </span>
    );
  }
  return (
    <div className="min-w-0">
      {row.primary_email && (
        <a
          href={`mailto:${row.primary_email}`}
          className="block truncate text-sm text-brand-700 hover:underline"
          onClick={(event) => event.stopPropagation()}
        >
          {row.primary_email}
        </a>
      )}
      {row.primary_phone && (
        <span className="block truncate text-xs text-ink-500">{row.primary_phone}</span>
      )}
      {row.contact_count > 1 && (
        <span className="text-xs text-ink-400">+{row.contact_count - 1} more</span>
      )}
    </div>
  );
}

function StatusCell({ row }: { row: BusinessRow }) {
  if (row.status === "completed") return null;
  const tone = row.status === "failed" ? "high" : "muted";
  return (
    <Badge tone={tone} title={row.failure_reason ?? undefined}>
      {row.status === "no_website" ? "no website" : row.failure_reason ?? row.status}
    </Badge>
  );
}

function TechCell({ row }: { row: BusinessRow }) {
  if (row.top_technologies.length === 0) {
    return <span className="text-xs text-ink-400">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {row.top_technologies.slice(0, 3).map((tech) => (
        <Badge
          key={tech.name}
          tone={tech.is_outdated ? "high" : "neutral"}
          title={tech.is_outdated ? `${tech.name} looks outdated` : (tech.category ?? undefined)}
        >
          {tech.name}
          {tech.version && <span className="opacity-70">{tech.version}</span>}
        </Badge>
      ))}
      {row.top_technologies.length > 3 && (
        <span className="self-center text-xs text-ink-400">
          +{row.top_technologies.length - 3}
        </span>
      )}
    </div>
  );
}

/**
 * The results table.
 *
 * Every column renders from the row the list endpoint already returned — no
 * per-row request. That is why `BusinessRow` is deliberately fat.
 */
export function ResultsTable({ rows }: { rows: BusinessRow[] }) {
  return (
    <>
      {/* Desktop: a real table, because this is tabular data people scan
          down a column and sort. */}
      <div className="scroll-x card hidden md:block">
        <table className="w-full min-w-[64rem] text-left text-sm">
          <thead className="border-b border-ink-200 bg-ink-50/60">
            <tr className="label">
              <th scope="col" className="px-4 py-2.5 font-medium">Business</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Contact</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Opp</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Lead</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Security</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Site</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Top opportunity</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Technology</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {rows.map((row) => (
              <tr key={row.id} className="group hover:bg-brand-50/40">
                <td className="max-w-[18rem] px-4 py-3">
                  <Link
                    to={`/businesses/${row.id}`}
                    className="block truncate font-medium text-ink-900 group-hover:text-brand-700"
                  >
                    {row.name}
                  </Link>
                  <div className="flex items-center gap-2">
                    <span className="truncate text-xs text-ink-500">{row.domain ?? "—"}</span>
                    <StatusCell row={row} />
                  </div>
                </td>
                <td className="max-w-[14rem] px-4 py-3"><ContactCell row={row} /></td>
                <td className="px-4 py-3 text-right"><ScorePill kind="opportunity" score={row.scores.opportunity} /></td>
                <td className="px-4 py-3 text-right"><ScorePill kind="lead" score={row.scores.lead} /></td>
                <td className="px-4 py-3 text-right"><ScorePill kind="security" score={row.scores.security} /></td>
                <td className="px-4 py-3 text-right"><ScorePill kind="website" score={row.scores.website} /></td>
                <td className="max-w-[20rem] px-4 py-3">
                  {row.top_opportunity ? (
                    <div className="flex items-start gap-2">
                      <UrgencyBadge urgency={row.top_opportunity.urgency} />
                      <span className="min-w-0 flex-1 truncate text-ink-700" title={row.top_opportunity.title}>
                        {row.top_opportunity.title}
                      </span>
                      {row.opportunity_count > 1 && (
                        <span className="tnum shrink-0 text-xs text-ink-400">
                          +{row.opportunity_count - 1}
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="text-xs text-ink-400">none found</span>
                  )}
                </td>
                <td className="px-4 py-3"><TechCell row={row} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: cards. A horizontally scrolling eight-column table on a
          phone is unusable, so the same data is restacked. */}
      <ul className="space-y-3 md:hidden">
        {rows.map((row) => (
          <li key={row.id} className="card p-4">
            <Link to={`/businesses/${row.id}`} className="block">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-ink-900">{row.name}</p>
                  <p className="truncate text-xs text-ink-500">{row.domain ?? "—"}</p>
                </div>
                <div className="text-right">
                  <ScorePill kind="opportunity" score={row.scores.opportunity} className="text-lg" />
                  <p className="label">opp</p>
                </div>
              </div>
            </Link>

            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-ink-100 pt-3 text-center">
              {(["lead", "security", "website"] as const).map((kind) => (
                <div key={kind}>
                  <ScorePill kind={kind} score={row.scores[kind]} />
                  <p className="label">{kind}</p>
                </div>
              ))}
            </div>

            <div className="mt-3 border-t border-ink-100 pt-3">
              <ContactCell row={row} />
            </div>

            {row.top_opportunity && (
              <div className="mt-3 flex items-start gap-2 border-t border-ink-100 pt-3">
                <UrgencyBadge urgency={row.top_opportunity.urgency} />
                <span className="min-w-0 flex-1 text-sm text-ink-700">
                  {row.top_opportunity.title}
                </span>
              </div>
            )}

            <div className={classNames("mt-3", row.top_technologies.length === 0 && "hidden")}>
              <TechCell row={row} />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
