/**
 * The REST contract, transcribed from /openapi.json.
 *
 * This file is the only description of the backend the UI has. It never
 * imports from, or reaches into, anything Python — the API is the boundary.
 *
 * Nullable fields are typed `| null` rather than optional on purpose. The
 * backend distinguishes "we looked and there is nothing" from "we could not
 * look", and several screens are required to render those differently. An
 * optional field would let a component quietly skip that distinction.
 */

export type ScanStatus =
  | "pending"
  | "discovering"
  | "analyzing"
  | "completed"
  | "failed"
  | "cancelled";

export type BusinessStatus = "pending" | "completed" | "failed" | "no_website";

export type Severity = "critical" | "high" | "medium" | "low" | "info";

/** `not_applicable` means the check could not be evaluated. It is NOT a pass
 *  and it is NOT a problem — see the DNS lookup-failure handling. */
export type FindingStatus = "pass" | "fail" | "warn" | "info" | "not_applicable";

export type Urgency = "critical" | "high" | "medium" | "low";

export type ScoreKey = "lead" | "website" | "security" | "opportunity";

export interface ScanSummary {
  id: string;
  status: ScanStatus;
  keyword: string | null;
  location: string | null;
  provider: string;
  total_businesses: number;
  completed_count: number;
  failed_count: number;
  /** Set when this scan re-runs an earlier one, which is what makes the
   *  comparison view reachable. */
  rerun_of_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ScanProgress {
  id: string;
  status: ScanStatus;
  total_businesses: number;
  completed_count: number;
  failed_count: number;
  percent_complete: number;
  /** The site being analysed right now. Shown by name so the user can see
   *  the run is alive rather than watching an anonymous spinner. */
  current_business: string | null;
  elapsed_seconds: number | null;
  error_message: string | null;
}

export interface ScoreSet {
  lead: number | null;
  website: number | null;
  security: number | null;
  opportunity: number | null;
}

export interface TechnologySummary {
  name: string;
  category: string | null;
  version: string | null;
  is_outdated: boolean | null;
}

export interface OpportunitySummary {
  rule_id: string;
  title: string;
  category: string;
  urgency: Urgency;
}

export interface BusinessRow {
  id: string;
  name: string;
  domain: string | null;
  website_url: string | null;
  city: string | null;
  country_code: string | null;
  status: BusinessStatus;
  failure_reason: string | null;
  /** null means no address was published on the site. It is never a guess,
   *  so the UI must show "none found" rather than an empty cell. */
  primary_email: string | null;
  primary_phone: string | null;
  contact_count: number;
  scores: ScoreSet;
  top_technologies: TechnologySummary[];
  opportunity_count: number;
  top_opportunity: OpportunitySummary | null;
  critical_findings: number;
  high_findings: number;
  scanned_at: string | null;
}

export interface FindingDetail {
  check_id: string;
  plugin_id: string;
  category: string;
  status: FindingStatus;
  severity: Severity;
  title: string;
  description: string;
  /** Never empty for a fail or warn. The backend refuses to construct one. */
  evidence: Record<string, unknown>;
  remediation: string | null;
}

export interface OpportunityDetail {
  rule_id: string;
  title: string;
  category: string;
  urgency: Urgency;
  /** Produced deterministically by the rule engine. The source of truth, and
   *  the version to put in front of a prospect. */
  description: string;
  /** An optional model rewrite. It never replaces `description`; both are
   *  returned so the defensible one is always available. */
  description_ai: string | null;
  pitch_angle: string;
  evidence: Record<string, unknown>;
  triggered_by: string[];
}

export interface ContactDetail {
  kind: string;
  category: string;
  value: string;
  /** The page it was found on. Every contact is traceable to a URL. */
  source_url: string;
}

export interface SnapshotMeta {
  captured_at: string;
  render_mode: string;
  status: string;
  page_count: number;
  duration_ms: number;
  final_url: string | null;
}

export interface ScoreBreakdown {
  total: number;
  components: Record<string, number>;
  confidence: number;
}

export interface BusinessDetail {
  id: string;
  scan_id: string;
  name: string;
  domain: string | null;
  website_url: string | null;
  final_url: string | null;
  city: string | null;
  country_code: string | null;
  status: BusinessStatus;
  failure_reason: string | null;
  failure_detail: string | null;
  contacts: ContactDetail[];
  primary_email: string | null;
  primary_phone: string | null;
  technologies: TechnologySummary[];
  findings: FindingDetail[];
  opportunities: OpportunityDetail[];
  /** Keyed by ScoreKey when present. */
  scores: Record<string, ScoreBreakdown> | null;
  snapshot: SnapshotMeta | null;
  analyzed_at: string | null;
}

export interface Pagination {
  total: number;
  limit: number;
  offset: number;
}

export interface BusinessListResponse {
  data: BusinessRow[];
  pagination: Pagination;
  scan_status: ScanStatus;
}

export interface ScanListResponse {
  data: ScanSummary[];
  pagination: Pagination;
}

export interface ScoreDelta {
  before: number | null;
  after: number | null;
  change: number | null;
}

export type ComparisonState = "added" | "removed" | "changed" | "unchanged";

export interface BusinessComparison {
  domain: string;
  name: string;
  state: ComparisonState;
  scores: Record<string, ScoreDelta>;
  opportunities_gained: string[];
  opportunities_resolved: string[];
  technologies_added: string[];
  technologies_removed: string[];
}

export interface ScanComparison {
  base_scan_id: string;
  compare_scan_id: string;
  total_compared: number;
  added: number;
  removed: number;
  changed: number;
  unchanged: number;
  businesses: BusinessComparison[];
}

export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  kind: string;
  depends_on: string[];
  provides: string[];
}

export interface HealthResponse {
  status: "ok";
  version: string;
}

export interface ReadinessResponse {
  status: "ready" | "degraded";
  database: boolean;
  rules_loaded: boolean;
  plugins: number;
  workers_running: boolean;
}

/** RFC 9457 Problem Details, which every error path returns. */
export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  correlation_id?: string | null;
  meta?: Record<string, unknown> | null;
  errors?: { field: string; code: string; message: string }[];
}

export interface CreateScanRequest {
  keyword?: string | null;
  location?: string | null;
  urls?: string[];
  provider?: "manual" | "csv_import";
  limit?: number;
}

export interface CsvValidationResult {
  created: false;
  valid_row_count: number;
  invalid_rows: { row: number; reason: string }[];
  detected_columns: Record<string, string> | null;
  preview: { name: string; domain: string }[];
}

export interface BusinessListParams {
  sort?: "opportunity_score" | "lead_score" | "security_score" | "website_score" | "name";
  order?: "asc" | "desc";
  status?: "completed" | "failed" | "no_website" | "all";
  has_contact?: boolean;
  min_opportunity_score?: number;
  limit?: number;
  offset?: number;
}

export const TERMINAL_STATUSES: readonly ScanStatus[] = ["completed", "failed", "cancelled"];

export function isTerminal(status: ScanStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}
