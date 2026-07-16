import { type ReviewStatus } from '@/lib/api';

const statusConfig: Record<string, { label: string; cls: string; dot: string; spinning?: boolean; spinBorder?: string; spinBorderTop?: string }> = {
  pending:   { label: 'Pending',   cls: 'bg-warning/10 text-warning border-warning/30',    dot: '', spinning: true, spinBorder: 'rgba(234, 179, 8, 0.25)', spinBorderTop: '#eab308' },
  running:   { label: 'Running',   cls: 'bg-blue-500/10 text-blue-400 border-blue-500/40', dot: '', spinning: true, spinBorder: 'rgba(59,130,246,0.25)', spinBorderTop: '#3b82f6' },
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
  const spinSize = size === 'md' ? 'w-3 h-3 border-[2.5px]' : 'w-2.5 h-2.5 border-2';

  return (
    <span className={`inline-flex items-center rounded-full font-medium border ${sizeCls} ${s.cls}`}>
      {s.spinning ? (
        <span
          className={`${spinSize} rounded-full flex-shrink-0 animate-spin`}
          style={{
            display: 'inline-block',
            borderStyle: 'solid',
            borderColor: s.spinBorder || 'rgba(59,130,246,0.25)',
            borderTopColor: s.spinBorderTop || '#3b82f6',
          }}
        />
      ) : (
        <span className={`${dotSize} rounded-full ${s.dot}`} />
      )}
      {s.label}
    </span>
  );
}
