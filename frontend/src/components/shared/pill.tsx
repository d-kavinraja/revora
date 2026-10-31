import { type ReactNode } from 'react';

export type PillTone = 'success' | 'warning' | 'error' | 'info' | 'muted' | 'brand';

const TONE_CLASSES: Record<PillTone, string> = {
  success: 'bg-success/10 text-success border-success/30',
  warning: 'bg-warning/10 text-warning border-warning/30',
  error: 'bg-error/10 text-error border-error/30',
  info: 'bg-info/10 text-info border-info/40',
  muted: 'bg-muted text-muted-foreground border-border',
  brand: 'bg-brand/10 text-brand border-brand/30',
};

const TONE_DOT: Record<PillTone, string> = {
  success: 'bg-success',
  warning: 'bg-warning',
  error: 'bg-error',
  info: 'bg-info',
  muted: 'bg-muted-foreground',
  brand: 'bg-brand',
};

export function Pill({
  tone = 'muted',
  children,
  className,
  dot = false,
}: {
  tone?: PillTone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium ${
        TONE_CLASSES[tone]
      } ${className ?? ''}`}
    >
      {dot && (
        <span
          aria-hidden="true"
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT[tone]}`}
        />
      )}
      {children}
    </span>
  );
}

/** Shared tone mapping for platform status strings (users, mappings, executions). */
export function toneForStatus(status: string | null | undefined): PillTone {
  const normalized = (status ?? '').toLowerCase();
  if (['active', 'ok', 'healthy', 'success', 'completed', 'valid', 'enabled'].includes(normalized)) {
    return 'success';
  }
  if (['pending', 'queued', 'running', 'stale', 'degraded', 'waiting', 'partial', 'disabled'].includes(normalized)) {
    return 'warning';
  }
  if (['missing', 'failed', 'invalid', 'down', 'error', 'timed_out', 'cancelled'].includes(normalized)) {
    return 'error';
  }
  return 'muted';
}
