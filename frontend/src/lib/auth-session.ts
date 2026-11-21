/** Pure helpers shared by user/admin session-confirmation flows. */

export type UserSessionFailureReason =
  | 'unauthorized'
  | 'unreachable'
  | 'disabled';

/** Classify an HTTP response from the user session-confirmation endpoint. */
export function classifyUserSessionFailure(
  status: number,
  data?: { detail?: unknown; code?: unknown } | null,
): UserSessionFailureReason {
  const detail = String(data?.detail ?? '').toLowerCase();
  const code = String(data?.code ?? '');
  if (code === 'account_disabled' || detail.includes('disabled') || status === 403) {
    return 'disabled';
  }
  if (status === 401) return 'unauthorized';
  return 'unreachable';
}

/** Read an Axios-like HTTP status without importing Axios into this module. */
export function sessionErrorStatus(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) return undefined;
  const status = (error as { response?: { status?: unknown } }).response?.status;
  return typeof status === 'number' ? status : undefined;
}

/** Only an explicit 401/403 proves an admin session is unusable. */
export function isDefinitiveSessionRejection(error: unknown): boolean {
  const status = sessionErrorStatus(error);
  return status === 401 || status === 403;
}

/**
 * Deduplicate an asynchronous operation while it is in flight.
 *
 * The app shell and OAuth callback can mount together and both request a
 * session restore. Sharing one request prevents a late pre-exchange 401 from
 * racing a successful post-exchange confirmation.
 */
export function createSingleFlight<T>(operation: () => Promise<T>): () => Promise<T> {
  let inFlight: Promise<T> | null = null;
  return () => {
    if (inFlight) return inFlight;
    const current = operation();
    inFlight = current;
    void current.finally(() => {
      if (inFlight === current) inFlight = null;
    }).catch(() => {
      // The caller observes the original promise. This catch handles only the
      // promise returned by finally(), avoiding an unhandled rejection.
    });
    return current;
  };
}
