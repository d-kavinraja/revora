'use client';

import { type ReviewStatus } from '@/lib/api';
import { Hourglass } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';

const statusConfig: Record<
  string,
  {
    label: string;
    cls: string;
    dot: string;
    spinning?: boolean;
    icon?: 'hourglass';
  }
> = {
  pending: {
    label: 'Pending',
    cls: 'bg-warning/10 text-warning border-warning/30',
    dot: '',
    icon: 'hourglass',
  },
  queued: {
    label: 'Queued',
    cls: 'bg-warning/10 text-warning border-warning/30',
    dot: '',
    icon: 'hourglass',
  },
  running: {
    label: 'Running',
    cls: 'bg-info/10 text-info border-info/40',
    dot: '',
    spinning: true,
  },
  completed: {
    label: 'Completed',
    cls: 'bg-success/10 text-success border-success/30',
    dot: 'bg-success',
  },
  failed: {
    label: 'Failed',
    cls: 'bg-error/10 text-error border-error/30',
    dot: 'bg-error',
  },
};

interface StatusBadgeProps {
  status: ReviewStatus | string;
  size?: 'sm' | 'md';
  queuePosition?: number;
}

export function StatusBadge({ status, size = 'sm', queuePosition }: StatusBadgeProps) {
  const reduceMotion = useReducedMotion();
  const s = statusConfig[status] ?? {
    label: status,
    cls: 'bg-muted text-muted-foreground border-border',
    dot: 'bg-muted-foreground',
  };
  const sizeCls =
    size === 'md' ? 'px-3 py-1 text-sm gap-1.5' : 'px-2.5 py-1 text-xs gap-1.5';
  const dotSize = size === 'md' ? 'w-2 h-2' : 'w-1.5 h-1.5';
  const spinSize = size === 'md' ? 'w-3 h-3 border-[2.5px]' : 'w-2.5 h-2.5 border-2';

  const showPosition =
    queuePosition !== undefined && (status === 'pending' || status === 'running');
  const label = showPosition ? `${s.label} #${queuePosition}` : s.label;

  return (
    <span
      className={`inline-flex items-center rounded-full border font-medium ${sizeCls} ${s.cls}`}
    >
      {s.icon === 'hourglass' ? (
        reduceMotion ? (
          <Hourglass
            size={size === 'md' ? 14 : 12}
            strokeWidth={2.5}
            className="shrink-0"
            aria-hidden="true"
          />
        ) : (
          <motion.span
            className="flex shrink-0 items-center justify-center"
            animate={{ opacity: [0.55, 1, 0.55], scale: [0.92, 1, 0.92] }}
            transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
            aria-hidden="true"
          >
            <Hourglass size={size === 'md' ? 14 : 12} strokeWidth={2.5} />
          </motion.span>
        )
      ) : s.spinning ? (
        <span
          aria-hidden="true"
          className={`${spinSize} shrink-0 rounded-full border-info/25 border-t-info ${
            reduceMotion ? '' : 'animate-spin'
          }`}
          style={{ borderStyle: 'solid' }}
        />
      ) : (
        <span
          aria-hidden="true"
          className={`${dotSize} shrink-0 rounded-full ${s.dot}`}
        />
      )}
      {label}
    </span>
  );
}
