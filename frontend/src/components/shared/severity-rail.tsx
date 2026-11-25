/**
 * The findings severity rail — the app's one signature element. Carries the
 * product's real subject (severity of code-review findings) as a compact,
 * typographic strip used on the dashboard and review detail header only.
 * Counts are real text (accessible); the bars scale to the largest count and
 * fill once on mount when motion is allowed (see .severity-rail-fill rules).
 */
export type SeverityCounts = {
  critical: number;
  high: number;
  medium: number;
  low: number;
  suggestions: number;
};

const SEGMENTS: {
  key: keyof SeverityCounts;
  label: string;
  fill: string;
  text: string;
}[] = [
  { key: 'critical', label: 'Critical', fill: 'bg-error', text: 'text-error' },
  { key: 'high', label: 'High', fill: 'bg-error/70', text: 'text-error' },
  { key: 'medium', label: 'Medium', fill: 'bg-warning', text: 'text-warning' },
  { key: 'low', label: 'Low', fill: 'bg-muted-foreground/50', text: 'text-muted-foreground' },
  { key: 'suggestions', label: 'Suggestions', fill: 'bg-info/70', text: 'text-info' },
];

export function SeverityRail({
  counts,
  className,
}: {
  counts: SeverityCounts;
  className?: string;
}) {
  const max = Math.max(counts.critical, counts.high, counts.medium, counts.low, counts.suggestions, 1);
  return (
    <div
      className={`rounded-xl border border-border bg-surface-1 px-4 py-3.5 ${className ?? ''}`}
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        {SEGMENTS.map((segment) => (
          <div key={segment.key} className="flex min-w-[132px] flex-1 items-center gap-2.5">
            <div
              className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-muted"
              aria-hidden="true"
            >
              <div
                className={`severity-rail-fill h-full rounded-full ${segment.fill}`}
                style={{ width: `${Math.max((counts[segment.key] / max) * 100, counts[segment.key] > 0 ? 6 : 0)}%` }}
              />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className={`font-heading text-lg font-bold leading-none ${segment.text}`}>
                {counts[segment.key]}
              </span>
              <span className="text-xs text-muted-foreground">{segment.label}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}