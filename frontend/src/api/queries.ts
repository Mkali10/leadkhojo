import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { ApiError } from "./client";
import { api } from "./endpoints";
import type {
  BusinessListParams,
  BusinessListResponse,
  CreateScanRequest,
  ScanProgress,
} from "./types";
import { isTerminal } from "./types";

/** Query keys in one place, so an invalidation cannot miss a screen. */
export const keys = {
  readiness: ["readiness"] as const,
  plugins: ["plugins"] as const,
  scans: ["scans"] as const,
  scanList: (limit: number, offset: number) => ["scans", "list", limit, offset] as const,
  scan: (id: string) => ["scans", id] as const,
  progress: (id: string) => ["scans", id, "progress"] as const,
  businesses: (id: string, params: BusinessListParams) =>
    ["scans", id, "businesses", params] as const,
  business: (id: string) => ["businesses", id] as const,
  comparison: (a: string, b: string) => ["compare", a, b] as const,
};

/** How often a running scan is polled. The endpoint is deliberately small;
 *  the backend documents ~2s as the intended cadence. */
const POLL_MS = 2000;

export function useReadiness() {
  return useQuery({
    queryKey: keys.readiness,
    queryFn: api.readiness,
    refetchInterval: 30_000,
    retry: false,
    // A degraded backend should surface quickly, not sit behind a stale value.
    staleTime: 0,
  });
}

export function usePlugins() {
  return useQuery({
    queryKey: keys.plugins,
    queryFn: api.plugins,
    // The loaded plugin set cannot change without restarting the server.
    staleTime: Infinity,
  });
}

export function useScans(limit = 50, offset = 0) {
  return useQuery({
    queryKey: keys.scanList(limit, offset),
    queryFn: () => api.listScans(limit, offset),
    refetchInterval: 10_000,
  });
}

export function useScan(scanId: string | undefined) {
  return useQuery({
    queryKey: keys.scan(scanId ?? ""),
    queryFn: () => api.getScan(scanId!),
    enabled: Boolean(scanId),
  });
}

/**
 * Poll progress until the scan reaches a terminal state, then stop.
 *
 * Polling forever after a scan finishes is the easy bug here: it burns a
 * request every two seconds for as long as the tab stays open.
 */
export function useScanProgress(scanId: string | undefined, enabled = true) {
  return useQuery<ScanProgress>({
    queryKey: keys.progress(scanId ?? ""),
    queryFn: () => api.getProgress(scanId!),
    enabled: Boolean(scanId) && enabled,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return POLL_MS;
      return isTerminal(data.status) ? false : POLL_MS;
    },
    // Keep polling when the tab is backgrounded: users start a scan and go
    // and do something else, and expect it finished when they come back.
    refetchIntervalInBackground: true,
  });
}

export function useBusinesses(
  scanId: string | undefined,
  params: BusinessListParams,
  options: { live?: boolean } = {},
) {
  return useQuery<BusinessListResponse>({
    queryKey: keys.businesses(scanId ?? "", params),
    queryFn: () => api.listBusinesses(scanId!, params),
    enabled: Boolean(scanId),
    // Rows land as each site finishes, so a running scan refreshes the table.
    refetchInterval: options.live ? 3000 : false,
    placeholderData: (previous) => previous,
  });
}

export function useBusiness(businessId: string | undefined) {
  return useQuery({
    queryKey: keys.business(businessId ?? ""),
    queryFn: () => api.getBusiness(businessId!),
    enabled: Boolean(businessId),
  });
}

export function useComparison(
  baseId: string | undefined,
  compareId: string | undefined,
  options?: Partial<UseQueryOptions<Awaited<ReturnType<typeof api.compareScans>>, ApiError>>,
) {
  return useQuery({
    queryKey: keys.comparison(baseId ?? "", compareId ?? ""),
    queryFn: () => api.compareScans(baseId!, compareId!),
    enabled: Boolean(baseId && compareId && baseId !== compareId),
    ...options,
  });
}

// ---------------------------------------------------------------- mutations

export function useCreateScan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateScanRequest) => api.createScan(body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.scans }),
  });
}

export function useCreateScanFromCsv() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.createScanFromCsv(file),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.scans }),
  });
}

export function useValidateCsv() {
  return useMutation({ mutationFn: (file: File) => api.validateCsv(file) });
}

export function useRerunScan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (scanId: string) => api.rerunScan(scanId),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.scans }),
  });
}

export function useCancelScan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (scanId: string) => api.cancelScan(scanId),
    onSuccess: (_data, scanId) => {
      client.invalidateQueries({ queryKey: keys.scans });
      client.invalidateQueries({ queryKey: keys.progress(scanId) });
    },
  });
}

export function useDeleteScan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (scanId: string) => api.deleteScan(scanId),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.scans }),
  });
}
