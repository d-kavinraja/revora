/**
 * Review History count helpers.
 *
 * `GET /reviews/{id}/history` returns two different collections:
 *   - `history`   → the review lifecycle rows that exist for the pull request
 *                   (one per Review row; the lifecycle model reuses a single
 *                   review row per PR, so this is typically 1),
 *   - `executions` → every execution recorded for the requested review.
 *
 * The backend applies no limit/offset to the execution query, so the length of
 * that list is the authoritative total number of executions for the review.
 * The collapsed Review History header renders that same number, which is why
 * it can never disagree with the expanded execution panel (both read the one
 * cached query response).
 */

export interface ReviewHistoryExecution {
  id: string;
  execution_number: number;
}

export interface ReviewHistoryPayload {
  current_review_id?: string;
  current_status?: string;
  history?: unknown[] | null;
  executions?: ReviewHistoryExecution[] | null;
}

/**
 * Total number of executions belonging to one review.
 *
 * Counts only the execution records of the requested review — never the
 * review lifecycle rows of the pull request, and never records of other
 * reviews.
 */
export function reviewExecutionCount(
  history: ReviewHistoryPayload | null | undefined,
): number {
  const executions = history?.executions;
  return Array.isArray(executions) ? executions.length : 0;
}

/**
 * Number of review lifecycle rows for the pull request.
 *
 * Kept separate from {@link reviewExecutionCount}: this is the size of the
 * "review history" list, which is not the number of executions.
 */
export function reviewLifecycleCount(
  history: ReviewHistoryPayload | null | undefined,
): number {
  const lifecycles = history?.history;
  return Array.isArray(lifecycles) ? lifecycles.length : 0;
}

/** Human label for the execution count, using Revora's "execution" wording. */
export function reviewHistoryCountLabel(count: number): string {
  const safe = Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
  return `${safe} ${safe === 1 ? 'execution' : 'executions'}`;
}
