/**
 * Honest metric display: a missing, null or non-finite value means the number
 * is *unknown* — it must never be rendered as a confirmed zero. Genuine zeros
 * pass through unchanged. Used wherever a metric can be absent because the
 * request failed or the backend did not report it.
 */
export function metricDisplay(value: number | null | undefined): number | '—' {
  return typeof value === 'number' && Number.isFinite(value) ? value : '—';
}