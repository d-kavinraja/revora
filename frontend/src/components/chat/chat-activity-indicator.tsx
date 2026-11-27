'use client';

/**
 * Provider-neutral, compact activity indicator used by both chat shells while
 * the AI is preparing, warming up, reviewing context, or generating a
 * response. The label is produced by `chat-activity.ts` so this component
 * never names infrastructure.
 *
 * Visual goals (per the activity-status redesign):
 *   - calm, small, pill-shaped
 *   - subtle pulse, suppressed under prefers-reduced-motion
 *   - readable in both light and dark themes
 *   - accessible: role=status, aria-live=polite, label mirrored as aria-label
 *
 * When `label` is null/empty the component renders nothing: the streamed
 * answer replaces the indicator and we never speak over it.
 */

interface ChatActivityIndicatorProps {
  label?: string | null;
  className?: string;
}

export function ChatActivityIndicator({
  label,
  className = '',
}: ChatActivityIndicatorProps) {
  if (!label) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      data-testid="chat-activity-indicator"
      className={`chat-ink inline-flex items-center gap-2 rounded-full border border-border/60 bg-surface-2/70 px-2.5 py-1 text-[11px] font-medium leading-none tracking-wide shadow-[0_1px_2px_rgb(0_0_0_/_0.04)] ${className}`}
    >
      <span aria-hidden className="relative inline-flex h-2 w-2">
        <span className="absolute inset-0 inline-flex animate-ping rounded-full bg-foreground/30 motion-reduce:animate-none" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-foreground/65" />
      </span>
      <span>{label}</span>
    </div>
  );
}

export default ChatActivityIndicator;
