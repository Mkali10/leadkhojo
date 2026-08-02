import type { ProblemDetail } from "./types";

/**
 * The single place the browser talks to the backend.
 *
 * Relative base URL by design: in development Vite proxies /api, and in
 * production the bundle is served from the same origin as the API. Baking a
 * host into the build is what makes a frontend that only works on the machine
 * it was built on.
 */
export const API_BASE = "/api/v1";

/** An error carrying the server's Problem Details, so the UI can show the
 *  server's own explanation instead of inventing one. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly correlationId: string | null;
  readonly fieldErrors: { field: string; message: string }[];

  constructor(status: number, problem: Partial<ProblemDetail>, fallback: string) {
    super(problem.detail || problem.title || fallback);
    this.name = "ApiError";
    this.status = status;
    this.code = problem.code ?? "unknown_error";
    this.detail = problem.detail ?? fallback;
    this.correlationId = problem.correlation_id ?? null;
    this.fieldErrors = (problem.errors ?? []).map((e) => ({
      field: e.field,
      message: e.message,
    }));
  }

  /** 404 is routine (a deleted scan, a stale link) and should not be dressed
   *  up as a failure the user must report. */
  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let problem: Partial<ProblemDetail> = {};
  try {
    problem = (await response.json()) as Partial<ProblemDetail>;
  } catch {
    // A non-JSON error body (a proxy timeout page, say). The status is all
    // we have, and it is better than pretending we parsed something.
  }
  return new ApiError(response.status, problem, `Request failed with ${response.status}`);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | undefined>;
}

function withQuery(path: string, query: RequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal, query } = options;

  const response = await fetch(`${API_BASE}${withQuery(path, query)}`, {
    method,
    signal,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Multipart upload, for the CSV endpoints. */
export async function upload<T>(path: string, file: File, query?: RequestOptions["query"]): Promise<T> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE}${withQuery(path, query)}`, {
    method: "POST",
    body: form,
  });

  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

function filenameFrom(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match?.[1] ? decodeURIComponent(match[1]) : fallback;
}

/**
 * Download an export.
 *
 * Fetched as a blob rather than pointing the browser at the URL: a plain link
 * to a failing endpoint navigates the user away to a raw JSON error page and
 * loses their place. This way a failure is an ApiError the page can show
 * in-place, and the filename the server chose is preserved.
 */
export async function download(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw await toApiError(response);

  const blob = await response.blob();
  const name = filenameFrom(response.headers.get("Content-Disposition"), fallbackName);
  const url = URL.createObjectURL(blob);

  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  // Revoking immediately can cancel the download in some browsers.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Health lives outside /api/v1, so it gets its own tiny helper. */
export async function fetchReadiness<T>(): Promise<T> {
  const response = await fetch("/readyz");
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}
