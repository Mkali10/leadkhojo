import { download, request, upload } from "./client";
import type {
  BusinessDetail,
  BusinessListParams,
  BusinessListResponse,
  CreateScanRequest,
  CsvValidationResult,
  PluginInfo,
  ReadinessResponse,
  ScanComparison,
  ScanListResponse,
  ScanSummary,
  ScanProgress,
} from "./types";
import { fetchReadiness } from "./client";

/** One function per endpoint, named for what the user is doing. */
export const api = {
  readiness: () => fetchReadiness<ReadinessResponse>(),

  plugins: () => request<PluginInfo[]>("/meta/plugins"),

  listScans: (limit = 50, offset = 0) =>
    request<ScanListResponse>("/scans", { query: { limit, offset } }),

  getScan: (scanId: string) => request<ScanSummary>(`/scans/${scanId}`),

  getProgress: (scanId: string) => request<ScanProgress>(`/scans/${scanId}/progress`),

  createScan: (body: CreateScanRequest) =>
    request<ScanSummary>("/scans", { method: "POST", body }),

  createScanFromCsv: (file: File) => upload<ScanSummary>("/scans/csv", file),

  /** Dry run. Creates nothing, so the user can check column detection before
   *  committing 400 rows to a scan. */
  validateCsv: (file: File) => upload<CsvValidationResult>("/scans/csv/validate", file),

  listBusinesses: (scanId: string, params: BusinessListParams = {}) =>
    request<BusinessListResponse>(`/scans/${scanId}/businesses`, {
      query: { ...params },
    }),

  getBusiness: (businessId: string) => request<BusinessDetail>(`/businesses/${businessId}`),

  rerunScan: (scanId: string) =>
    request<ScanSummary>(`/scans/${scanId}/rerun`, { method: "POST" }),

  compareScans: (baseId: string, compareId: string) =>
    request<ScanComparison>(`/scans/${baseId}/compare/${compareId}`),

  cancelScan: (scanId: string) =>
    request<ScanSummary>(`/scans/${scanId}/cancel`, { method: "POST" }),

  deleteScan: (scanId: string) => request<void>(`/scans/${scanId}`, { method: "DELETE" }),

  downloadScanCsv: (scanId: string) =>
    download(`/exports/scans/${scanId}/csv`, `leadkhojo-${scanId}.csv`),

  downloadScanPdf: (scanId: string) =>
    download(`/exports/scans/${scanId}/pdf`, `leadkhojo-${scanId}.pdf`),

  downloadBusinessPdf: (businessId: string, domain: string | null) =>
    download(
      `/exports/businesses/${businessId}/pdf`,
      `leadkhojo-${(domain ?? businessId).replace(/\./g, "-")}.pdf`,
    ),
};
