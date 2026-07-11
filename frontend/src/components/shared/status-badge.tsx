import { type ReviewStatus } from '@/lib/api';

const statusConfig: Record<string, { label: string; cls: string; dot: string }> = {
  pending:   { label: 'Pending',   cls: 'bg-warning/10 text-warning border-warning/30',    dot: 'bg-warning' },
  running:   { label: 'Running',   cls: 'bg-info/10 text-info border-info/30',             dot: 'bg-info animate-pulse' },
  completed: { label: 'Completed', cls: 'bg-success/10 text-success border-success/30',    dot: 'bg-success' },
  failed:    { label: 'Failed',    cls: 'bg-error/10 text-error border-error/30',           dot: 'bg-error' },
};

interface StatusBadgeProps {
  status: ReviewStatus | string;
  size?: 'sm' | 'md';
}

export function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  const s = statusConfig[status] ?? { label: status, cls: 'bg-muted text-muted-foreground border-border', dot: 'bg-muted-foreground' };
  const sizeCls = size === 'md'
    ? 'px-3 py-1 text-sm gap-1.5'
    : 'px-2.5 py-0.5 text-xs gap-1.5';
  const dotSize = size === 'md' ? 'w-2 h-2' : 'w-1.5 h-1.5';

  return (
    <span className={`inline-flex items-center rounded-full font-medium border ${sizeCls} ${s.cls}`}>
      <span className={`${dotSize} rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
