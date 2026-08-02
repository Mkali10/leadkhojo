import type { TechnologySummary } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { humanize } from "@/lib/format";

export function TechnologyList({ technologies }: { technologies: TechnologySummary[] }) {
  if (technologies.length === 0) {
    return <p className="text-sm text-ink-500">No technologies were fingerprinted on this site.</p>;
  }

  const byCategory = new Map<string, TechnologySummary[]>();
  for (const tech of technologies) {
    const key = tech.category ?? "other";
    const bucket = byCategory.get(key);
    if (bucket) bucket.push(tech);
    else byCategory.set(key, [tech]);
  }

  return (
    <div className="space-y-3">
      {[...byCategory.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([category, items]) => (
          <div key={category}>
            <p className="label mb-1.5">{humanize(category)}</p>
            <div className="flex flex-wrap gap-1.5">
              {items.map((tech) => (
                <Badge
                  key={tech.name}
                  tone={tech.is_outdated ? "high" : "neutral"}
                  title={
                    tech.is_outdated
                      ? "A newer release exists — this is a concrete thing to talk about"
                      : undefined
                  }
                >
                  {tech.name}
                  {tech.version && <span className="font-mono opacity-70">{tech.version}</span>}
                  {tech.is_outdated && <span aria-hidden="true">·</span>}
                  {tech.is_outdated && <span>outdated</span>}
                </Badge>
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}
