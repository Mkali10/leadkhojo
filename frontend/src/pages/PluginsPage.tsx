import { usePlugins } from "@/api/queries";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { ErrorState, Loading } from "@/components/ui/Feedback";

/**
 * What the engine actually runs, read from the server.
 *
 * This exists so "do you detect Craft CMS?" has an answer that is a URL
 * rather than a code read — and so the execution order, which is derived
 * from declared dependencies, is visible rather than folklore.
 */
export function PluginsPage() {
  const { data, isPending, error, refetch } = usePlugins();

  return (
    <>
      <PageHeader
        title="Checks"
        subtitle="The analysis plugins loaded on this server, in the order they run."
        back={{ to: "/", label: "Dashboard" }}
      />

      {isPending ? (
        <Loading />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <ol className="space-y-3">
          {data?.map((plugin, index) => (
            <li key={plugin.id} className="card p-4">
              <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
                <span className="tnum mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-ink-100 text-xs font-semibold text-ink-600">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-medium text-ink-900">{plugin.name}</h2>
                    <code className="text-xs text-ink-400">{plugin.id}</code>
                    <Badge tone={plugin.kind === "synthesizer" ? "brand" : "neutral"}>
                      {plugin.kind}
                    </Badge>
                    <span className="text-xs text-ink-400">v{plugin.version}</span>
                  </div>

                  <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[6rem_1fr]">
                    <dt className="text-ink-500">Produces</dt>
                    <dd className="flex flex-wrap gap-1">
                      {plugin.provides.length ? (
                        plugin.provides.map((item) => (
                          <code key={item} className="rounded bg-ink-50 px-1.5 py-0.5 text-ink-700">
                            {item}
                          </code>
                        ))
                      ) : (
                        <span className="text-ink-400">—</span>
                      )}
                    </dd>

                    <dt className="text-ink-500">Needs first</dt>
                    <dd className="flex flex-wrap gap-1">
                      {plugin.depends_on.length ? (
                        plugin.depends_on.map((item) => (
                          <code key={item} className="rounded bg-ink-50 px-1.5 py-0.5 text-ink-700">
                            {item}
                          </code>
                        ))
                      ) : (
                        <span className="text-ink-400">nothing</span>
                      )}
                    </dd>
                  </dl>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
