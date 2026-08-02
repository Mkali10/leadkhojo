import { Select } from "@/components/ui/Field";
import type { FilterState } from "./filters";

const SORTS = [
  { value: "opportunity_score", label: "Opportunity score" },
  { value: "lead_score", label: "Lead score" },
  { value: "security_score", label: "Security score" },
  { value: "website_score", label: "Website score" },
  { value: "name", label: "Name" },
];

const STATUSES = [
  { value: "completed", label: "Analysed" },
  { value: "failed", label: "Failed" },
  { value: "no_website", label: "No website" },
  { value: "all", label: "All" },
];

const CONTACTS = [
  { value: "", label: "Any contact" },
  { value: "true", label: "Has contact" },
  { value: "false", label: "No contact" },
];

export function ResultFilters({
  filters,
  onChange,
  total,
}: {
  filters: FilterState;
  onChange: (next: FilterState) => void;
  total: number;
}) {
  // Any filter change resets paging: staying on page 4 of a narrower result
  // set shows an empty table and looks like a bug.
  const patch = (next: Partial<FilterState>) => onChange({ ...filters, ...next, offset: 0 });

  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
      <Select
        label="Sort by"
        options={SORTS}
        value={filters.sort}
        onChange={(e) => patch({ sort: e.target.value as FilterState["sort"] })}
      />
      <Select
        options={[
          { value: "desc", label: "High to low" },
          { value: "asc", label: "Low to high" },
        ]}
        value={filters.order}
        onChange={(e) => patch({ order: e.target.value as FilterState["order"] })}
      />
      <Select
        label="Show"
        options={STATUSES}
        value={filters.status}
        onChange={(e) => patch({ status: e.target.value as FilterState["status"] })}
      />
      <Select
        options={CONTACTS}
        value={filters.has_contact === undefined ? "" : String(filters.has_contact)}
        onChange={(e) =>
          patch({ has_contact: e.target.value === "" ? undefined : e.target.value === "true" })
        }
      />
      <span className="tnum ml-auto text-sm text-ink-500">
        {total} {total === 1 ? "business" : "businesses"}
      </span>
    </div>
  );
}
