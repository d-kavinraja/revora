'use client';

import { useEffect, useRef } from 'react';
import { ChevronDownIcon } from 'lucide-react';
import type { ContextMeter } from '@/lib/chat-state';

interface ChatContextUsageProps {
  contextInfo: ContextMeter;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ChatContextUsage({ contextInfo, open, onOpenChange }: ChatContextUsageProps) {
  const contextRef = useRef<HTMLDivElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!contextRef.current?.contains(event.target as Node)) onOpenChange(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onOpenChange(false);
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onOpenChange]);

  // On narrow screens the header's containing block can clip the popover. Keep
  // the same anchored desktop layout while spanning the viewport on mobile.
  useEffect(() => {
    if (!open || !contextRef.current || !popoverRef.current) return;
    const applyPosition = () => {
      if (!contextRef.current || !popoverRef.current) return;
      if (window.innerWidth < 640) {
        const rect = contextRef.current.getBoundingClientRect();
        Object.assign(popoverRef.current.style, {
          position: 'fixed',
          top: `${rect.bottom + 8}px`,
          left: '12px',
          right: '12px',
          width: 'auto',
          maxWidth: 'none',
        });
      } else {
        Object.assign(popoverRef.current.style, {
          position: '',
          top: '',
          left: '',
          right: '',
          width: '',
          maxWidth: '',
        });
      }
    };
    applyPosition();
    window.addEventListener('resize', applyPosition);
    return () => window.removeEventListener('resize', applyPosition);
  }, [open]);

  return (
    <div className="relative" ref={contextRef}>
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className="chat-ink inline-flex h-10 min-h-8 shrink-0 items-center gap-1.5 rounded-lg border border-border/60 px-2.5 text-xs transition hover:bg-muted/60 hover:text-foreground md:h-8 md:w-auto"
        aria-label={`Context information: ${contextInfo.usedPct !== null
          ? `${contextInfo.usedPct}% of the window used by the prompt`
          : `${contextInfo.promptTokens.toLocaleString()} estimated prompt tokens`}`}
        aria-expanded={open}
        title="Context information"
      >
        <span className="max-sm:hidden">Context</span>
        {contextInfo.usedPct !== null ? <span className="chat-ink tabular-nums">{contextInfo.usedPct}%</span> : null}
        <ChevronDownIcon size={13} className={`transition ${open ? 'rotate-180' : ''}`} />
      </button>
      {open ? (
        <div
          ref={popoverRef}
          className="absolute right-0 top-full z-50 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-popover px-4 py-3.5 text-popover-foreground shadow-xl sm:w-[340px]"
        >
          <div className="flex min-w-0 items-center justify-between gap-3 text-xs">
            <span className="min-w-0 truncate font-semibold text-foreground">Prompt usage</span>
            <span className="min-w-0 truncate tabular-nums text-muted-foreground">
              {contextInfo.contextWindow
                ? `${contextInfo.promptTokens.toLocaleString()} / ${contextInfo.contextWindow.toLocaleString()}`
                : `${contextInfo.promptTokens.toLocaleString()} est. prompt tokens`}
            </span>
          </div>
          {contextInfo.contextWindow ? (
            <>
              <div className="my-3 h-2 w-full overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-brand transition-[width] duration-300" style={{ width: `${contextInfo.usedPct ?? 0}%` }} />
              </div>
              <div className="grid min-w-0 grid-cols-2 gap-4">
                <div className="min-w-0">
                  <span className="block text-sm font-semibold tabular-nums text-foreground">{contextInfo.usedPct}%</span>
                  <span className="text-xs text-muted-foreground">of window used by prompt</span>
                </div>
                <div className="min-w-0 text-right">
                  <span className="block truncate text-sm font-semibold tabular-nums text-foreground">{contextInfo.remaining?.toLocaleString()}</span>
                  <span className="text-xs text-muted-foreground">window left</span>
                </div>
              </div>
            </>
          ) : (
            <p className="my-3 text-xs leading-relaxed text-muted-foreground">
              This model does not report a context window. Revora keeps a conservative{' '}
              {contextInfo.outputTokens.toLocaleString()}-token reply reserve and fits the prompt
              within the fixed legacy message and character limits instead of guessing.
            </p>
          )}
          <div className="my-3 border-t border-border/70" />
          <div className="min-w-0 space-y-1 text-xs">
            <ContextRow label="Messages in context" value={contextInfo.messages.toLocaleString()} />
            <ContextRow label="Prompt estimate" value={`${contextInfo.promptTokens.toLocaleString()} tokens`} />
            <ContextRow label="Reply reserve" value={`${contextInfo.outputTokens.toLocaleString()} tokens`} />
            <ContextRow label="Safety headroom" value={`${contextInfo.headroom.toLocaleString()} tokens`} />
            <ContextRow label="Reserved for next request" value={`${contextInfo.nextRequestTokens.toLocaleString()} tokens`} />
            {contextInfo.spareAfterNextRequest !== null ? (
              <ContextRow
                label="Spare after next request"
                value={contextInfo.nextRequestFits
                  ? `${contextInfo.spareAfterNextRequest.toLocaleString()} tokens`
                  : `${Math.abs(contextInfo.spareAfterNextRequest).toLocaleString()} tokens over`}
                valueClassName={contextInfo.nextRequestFits ? 'text-foreground' : 'text-warning'}
              />
            ) : null}
            <ContextRow label="Source" value="Next request estimate" />
            {contextInfo.historicalTokens !== null ? (
              <ContextRow
                label="Last response (secondary)"
                value={`${contextInfo.historicalTokens.toLocaleString()} tokens`}
                valueClassName="text-muted-foreground"
              />
            ) : null}
          </div>
          {contextInfo.clipped ? (
            <p className="mt-2 text-xs leading-relaxed text-warning">
              The newest turn was clipped to fit this window. The stored message is unchanged.
            </p>
          ) : null}
          <p className="mt-3 border-t border-border/50 pt-2.5 text-xs leading-relaxed text-muted-foreground">
            The bar and percentage count this chat&apos;s fitted prompt only. Reply reserve and
            safety headroom are separate reservations for the next request, not consumed context.
            Last-response tokens are secondary and never the numerator.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function ContextRow({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 py-1">
      <span className="min-w-0 text-muted-foreground">{label}</span>
      <span className={`min-w-0 font-medium tabular-nums ${valueClassName ?? 'text-foreground'}`}>{value}</span>
    </div>
  );
}
