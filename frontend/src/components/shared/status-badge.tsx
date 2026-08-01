import { type ReviewStatus } from '@/lib/api';
import { Hourglass } from 'lucide-react';
import { motion } from 'framer-motion';

const statusConfig: Record<string, { label: string; cls: string; dot: string; spinning?: boolean; icon?: 'hourglass'; spinBorder?: string; spinBorderTop?: string }> = {
  pending:   { label: 'Pending',   cls: 'bg-warning/10 text-warning border-warning/30',    dot: '', icon: 'hourglass' },
  queued:    { label: 'Queued',    cls: 'bg-warning/10 text-warning border-warning/30',    dot: '', icon: 'hourglass' },
  running:   { label: 'Running',   cls: 'bg-blue-500/10 text-blue-400 border-blue-500/40', dot: '', spinning: true, spinBorder: 'rgba(59,130,246,0.25)', spinBorderTop: '#3b82f6' },
  completed: { label: 'Completed', cls: 'bg-success/10 text-success border-success/30',    dot: 'bg-success' },
  failed:    { label: 'Failed',    cls: 'bg-error/10 text-error border-error/30',           dot: 'bg-error' },
};

interface StatusBadgeProps {
  status: ReviewStatus | string;
  size?: 'sm' | 'md';
  queuePosition?: number;
}

export function StatusBadge({ status, size = 'sm', queuePosition }: StatusBadgeProps) {
  const s = statusConfig[status] ?? { label: status, cls: 'bg-muted text-muted-foreground border-border', dot: 'bg-muted-foreground' };
  const sizeCls = size === 'md'
    ? 'px-3 py-1 text-sm gap-1.5'
    : 'px-2.5 py-0.5 text-xs gap-1.5';
  const dotSize = size === 'md' ? 'w-2 h-2' : 'w-1.5 h-1.5';
  const spinSize = size === 'md' ? 'w-3 h-3 border-[2.5px]' : 'w-2.5 h-2.5 border-2';

  // Show numbered position badge for active statuses (pending/running)
  const showPosition = queuePosition !== undefined && (status === 'pending' || status === 'running');
  const label = showPosition ? `${s.label} #${queuePosition}` : s.label;

  return (
    <span className={`inline-flex items-center rounded-full font-medium border ${sizeCls} ${s.cls}`}>
      {s.icon === 'hourglass' ? (
        <motion.span
          className="flex items-center justify-center flex-shrink-0 text-warning"
          animate={{ opacity: [0.55, 1, 0.55], scale: [0.92, 1, 0.92] }}
          transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
        >
          <Hourglass size={size === 'md' ? 14 : 12} strokeWidth={2.5} />
        </motion.span>
      ) : s.spinning ? (
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
      {label}
    </span>
  );
}
