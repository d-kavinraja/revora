/**
 * Shared browser-to-API transport configuration and error classification.
 *
 * `USE_API_PROXY` is the single decision consumed by BOTH the axios client
 * (`src/lib/api.ts`) and the Next.js `/api/v1` rewrite (`next.config.ts`).
 * Importing one module means the browser can never request a same-origin
 * `/api/v1` path that the server did not install (or the reverse).
 *
 * The backend host stays server-side (`BACKEND_ORIGIN`) and is never emitted
 * to the browser in proxy mode. Dependency-free on purpose so the pure
 * helpers can be exercised by the existing `node --test` frontend suite.
 */

export type ApiEnvironment = Record<string, string | undefined>;

const DEFAULT_DIRECT_API_URL = "http://127.0.0.1:8000/api/v1";
const DEFAULT_LOCAL_BACKEND_ORIGIN = "http://127.0.0.1:8000";

/** Resolve the browser's API base from one explicit environment snapshot. */
export function resolveApiBase(env: ApiEnvironment = process.env): {
  useProxy: boolean;
  apiBase: string;
} {
  // Cookie-backed authentication is reliable only when the browser talks to
  // the frontend origin and Next forwards the request. Make that the default;
  // direct cross-origin mode is an explicit local-development opt-out.
  const useProxy = env.NEXT_PUBLIC_USE_API_PROXY !== "false";
  return {
    useProxy,
    apiBase: useProxy
      ? "/api/v1"
      : env.NEXT_PUBLIC_API_URL || DEFAULT_DIRECT_API_URL,
  };
}

// NEXT_PUBLIC_* values must be referenced statically for Next.js to inline
// them into the browser bundle. Passing `process.env` through a function and
// looking up keys dynamically is explicitly unsupported by Next.js and made
// production builds silently fall back to 127.0.0.1.
const browserEnvironment: ApiEnvironment = {
  NEXT_PUBLIC_USE_API_PROXY: process.env.NEXT_PUBLIC_USE_API_PROXY,
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
};

const resolved = resolveApiBase(browserEnvironment);

/** True when the browser talks to the same-origin `/api/v1` proxy. */
export const USE_API_PROXY = resolved.useProxy;

/** Base URL used by every apiClient call, health ping, SSE and media URL. */
export const API_BASE = resolved.apiBase;

/** Accept a bare origin or one already ending in `/api/v1`. */
export function normalizeBackendOrigin(value: string | undefined): string {
  return (value ?? "")
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/api\/v1$/, "");
}

/**
 * Resolve the Next.js rewrite. The rewrite exists only in proxy mode and
 * needs a server-side destination. A missing destination is returned as an
 * error so `next.config.ts` fails loudly instead of silently disagreeing
 * with the browser's `/api/v1` base.
 */
export function resolveRewriteDestination(env: ApiEnvironment = process.env): {
  useProxy: boolean;
  destination: string | null;
  error: string | null;
} {
  const { useProxy } = resolveApiBase(env);
  if (!useProxy) return { useProxy: false, destination: null, error: null };

  const configuredOrigin =
    env.BACKEND_ORIGIN ||
    (env.NEXT_PUBLIC_API_URL?.startsWith("http://") ||
    env.NEXT_PUBLIC_API_URL?.startsWith("https://")
      ? env.NEXT_PUBLIC_API_URL
      : undefined);
  if (!configuredOrigin && env.NODE_ENV === "production") {
    return {
      useProxy: true,
      destination: null,
      error:
        "Same-origin API proxying requires BACKEND_ORIGIN (server-only) in production.",
    };
  }
  const origin = normalizeBackendOrigin(
    configuredOrigin || DEFAULT_LOCAL_BACKEND_ORIGIN,
  );
  if (!origin) {
    return {
      useProxy: true,
      destination: null,
      error:
        "NEXT_PUBLIC_USE_API_PROXY=true requires BACKEND_ORIGIN (server-only) so the /api/v1 rewrite has a destination.",
    };
  }
  return {
    useProxy: true,
    destination: `${origin}/api/v1/:path*`,
    error: null,
  };
}

/**
 * True only when the request failed before an HTTP response arrived.
 * Duck-typed (no axios import) so this stays usable in plain Node tests.
 */
export function isApiTransportError(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false;
  const candidate = err as {
    isAxiosError?: unknown;
    response?: unknown;
    code?: unknown;
  };
  if (candidate.response != null) return false;
  if (candidate.isAxiosError === true) return true;
  const code = String(candidate.code ?? "");
  return (
    code === "ERR_NETWORK" ||
    code === "ECONNABORTED" ||
    code === "ERR_CANCELED"
  );
}

/**
 * Human-readable API error. A received response keeps the backend's detail
 * and status; a transport failure is reported as a connectivity problem and
 * is never presented as a validation/policy error.
 */
export function apiErrorMessage(
  err: unknown,
  apiBase: string = API_BASE,
): string {
  if (typeof err === "object" && err !== null) {
    const candidate = err as {
      response?: { status?: number; data?: unknown };
      message?: unknown;
    };
    const response = candidate.response;
    if (response) {
      const data = response.data as { detail?: unknown } | null | undefined;
      const detail = data?.detail;
      if (typeof detail === "string" && detail.trim()) return detail;
      if (detail && typeof detail === "object" && "message" in detail) {
        return String((detail as { message: unknown }).message);
      }
      return typeof response.status === "number"
        ? `The backend rejected the request (HTTP ${response.status}).`
        : "The backend rejected the request.";
    }
    if (isApiTransportError(err)) {
      return `Could not reach the backend (${apiBase}). Check that the API server is running and reachable, then try again.`;
    }
    if (typeof candidate.message === "string" && candidate.message) {
      return candidate.message;
    }
  }
  return "Something went wrong. Please try again.";
}
