import type { BusinessListParams } from "@/api/types";

/** Kept out of the component file so Fast Refresh stays reliable — a module
 *  that exports both a component and constants loses it. */
export interface FilterState extends BusinessListParams {
  sort: NonNullable<BusinessListParams["sort"]>;
  order: NonNullable<BusinessListParams["order"]>;
  status: NonNullable<BusinessListParams["status"]>;
}

export const DEFAULT_FILTERS: FilterState = {
  sort: "opportunity_score",
  order: "desc",
  // Failed sites and businesses without a website are hidden by default: the
  // table is a work queue, and a row we could not analyse is not work.
  status: "completed",
  limit: 50,
  offset: 0,
};
