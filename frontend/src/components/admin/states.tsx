import { type ReactNode } from 'react';
import { AlertTriangle, Info } from 'lucide-react';

/**
 * Single error surface for admin queries. Keeps the existing `role="alert"`
 * contract and the "Try again" affordance; only the presentation is shared.
 */
export function QueryError({
  message,
  onRetry,
  className,
}: {
  message: string;
  onRetry: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={`flex items-start gap-3 rounded-xl border border-error/40 bg-error/10 p-4 text-sm text-error ${
        className ?? ''
      }`}
    >
      <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0">
        <p className="font-medium">{message}</p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 cursor-pointer rounded text-sm underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          Try again
        </button>
      </div>
    </div>
  );
}

export function InlineEmpty({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
      <Info size={14} className="shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}

/**
 * Explicit "this source did not report" reading. Never substitutes a zero,
 * never guesses: the hatch and mono reason mark the value as unrecorded.
 */
export function UnrecordedValue({
  label,
  reason,
  className,
}: {
  label: string;
  reason?: string | null;
  className?: string;
}) {
  return (
    <div className={className}>
      <p className="admin-figure text-lg font-semibold text-muted-foreground">
        {label}
      </p>
      {reason && (
        <p className="mt-1 font-mono text-[11px] leading-relaxed text-muted-foreground">
          {reason}
        </p>
      )}
    </div>
  );
}

export function AdminLoading({ label }: { label: string }) {
  return (
    <div
      role="status"
      className="flex items-center gap-3 rounded-xl border border-border bg-surface-1 p-5 text-sm text-muted-foreground"
    >
      <span
        className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-border border-t-brand"
        aria-hidden="true"
      />
      {label}
    </div>
  );
}
