'use client';

import { useRef } from 'react';
import Link from 'next/link';
import { MessageCircleIcon, MoveRightIcon } from '@animateicons/react/lucide';
import { Hourglass } from 'lucide-react';
import { motion } from 'framer-motion';
import { ProviderIcon } from '@/components/ui/provider-icon';
import BorderGlow from '@/components/ui/BorderGlow';
import { StatusBadge } from '@/components/shared/status-badge';
import { formatDateTimeWithRelative } from '@/components/shared/time-ago';
import { Review } from '@/lib/api';

export function ReviewItem({ review, queuePosition }: { review: Review; queuePosition?: number }) {
  const iconRef = useRef<any>(null);
  const arrowRef = useRef<any>(null);

  const iconSlot = (
    <div className="shrink-0">
      <div className="w-9 h-9 rounded-lg bg-white/[0.04] flex items-center justify-center text-muted-foreground group-hover:text-brand transition-colors">
        <MessageCircleIcon ref={iconRef} size={16} isAnimated={false} />
      </div>
    </div>
  );

  const pendingIconSlot = (
    <div className="shrink-0">
      <div className="w-9 h-9 rounded-lg bg-warning/10 border border-warning/25 flex items-center justify-center text-warning">
        <motion.div
          animate={{ opacity: [0.55, 1, 0.55], scale: [0.9, 1, 0.9] }}
          transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
        >
          <Hourglass size={16} strokeWidth={2} />
        </motion.div>
      </div>
    </div>
  );

  const renderContent = (icon: React.ReactNode) => (
    <div className="flex items-start gap-3">
      {icon}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className="font-semibold text-foreground truncate text-sm">
            {review.pull_request?.title ?? 'Pull Request'}
          </span>
          <StatusBadge status={review.status} queuePosition={queuePosition} />
        </div>
        <div className="flex items-center gap-2 mt-1.5 text-xs flex-wrap">
          <span className="text-brand font-medium">{review.repository?.full_name}</span>
          <span className="text-border">&#183;</span>
          <span className="text-foreground font-medium">PR #{review.pull_request?.pr_number}</span>
          <span className="text-border">&#183;</span>
          <span className="text-muted-foreground">@{review.pull_request?.author}</span>
          <span className="text-border">&#183;</span>
          <span className="text-muted-foreground/70">{formatDateTimeWithRelative(review.created_at)}</span>
          {review.stats && (review.stats as Record<string, string>).provider && (
            <>
              <span className="text-border">&#183;</span>
              <span className="flex items-center gap-1.5 px-1.5 py-0.5 rounded-md bg-white/[0.06] border border-white/[0.05] text-[9px] uppercase tracking-wider font-semibold text-muted-foreground">
                <ProviderIcon slug={(review.stats as Record<string, string>).provider} size={10} />
                {(review.stats as Record<string, string>).provider} &middot; {(review.stats as Record<string, string>).model}
              </span>
            </>
          )}
        </div>
        {review.status === 'pending' && (
          <div className="flex items-center gap-1.5 mt-2 text-[11px] text-warning/80">
            <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse flex-shrink-0" />
            <span>Waiting for an available worker&hellip;</span>
          </div>
        )}
        {review.status === 'failed' && review.error_message && (
          <div className="mt-2 p-2.5 bg-error/5 border border-error/20 rounded-lg text-xs font-mono text-error/90 whitespace-pre-wrap break-all">
            {review.error_message}
          </div>
        )}
      </div>
      <MoveRightIcon ref={arrowRef} size={16} isAnimated={false} className="text-border group-hover:text-brand transition-colors shrink-0 mt-2" />
    </div>
  );

  const innerProps = {
    onMouseEnter: () => {
      iconRef.current?.startAnimation();
      arrowRef.current?.startAnimation();
    },
    onMouseLeave: () => {
      iconRef.current?.stopAnimation();
      arrowRef.current?.stopAnimation();
    }
  };

  if (review.status === 'pending') {
    const estimatedStart = queuePosition !== undefined ? Math.max(5, Math.round(queuePosition * 7.5)) : undefined;
    return (
      <div className="relative w-full rounded-xl opacity-[0.93] ring-1 ring-warning/25 shadow-[0_0_28px_-8px_rgba(234,179,8,0.35)] hover:shadow-[0_0_36px_-6px_rgba(234,179,8,0.5)] transition-all duration-300">
        <BorderGlow
          animated={false}
          borderRadius={12}
          className="w-full rounded-xl"
          backgroundColor="var(--color-surface-1)"
          glowColor="38 92 50"
          colors={['#f59e0b', '#fbbf24', '#fcd34d']}
        >
          <Link href={`/reviews/${review.id}`} {...innerProps} className="cursor-target block p-4 group relative rounded-xl overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-[2px] bg-warning/10 overflow-hidden rounded-t-xl">
              <motion.div
                className="h-full w-1/3 bg-gradient-to-r from-transparent via-amber-400 to-transparent"
                animate={{ x: ['-100%', '400%'] }}
                transition={{ duration: 2.8, repeat: Infinity, ease: 'linear' }}
              />
            </div>
            {queuePosition !== undefined && (
              <div className="absolute top-3 right-3 z-10 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-200 bg-surface-2/95 border border-warning/30 rounded-lg px-3 py-2 shadow-xl">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-warning">
                  <Hourglass size={11} strokeWidth={2.5} />
                  Queue Position: #{queuePosition}
                </div>
                {estimatedStart !== undefined && (
                  <div className="text-[10px] text-muted-foreground mt-1">Estimated Start: ~{estimatedStart}s</div>
                )}
              </div>
            )}
            {renderContent(pendingIconSlot)}
          </Link>
        </BorderGlow>
      </div>
    );
  }

  if (review.status === 'running') {
    return (
      <BorderGlow
        animated={true}
        borderRadius={12}
        className="w-full mb-0 rounded-xl"
        backgroundColor="var(--color-surface-1)"
        glowColor="192 100 64"
      >
        <Link href={`/reviews/${review.id}`} {...innerProps} className="cursor-target block p-4 group">
          {renderContent(iconSlot)}
        </Link>
      </BorderGlow>
    );
  }

  return (
    <Link
      href={`/reviews/${review.id}`}
      {...innerProps}
      className="cursor-target block rounded-xl border border-border bg-surface-1 hover:border-brand/30 transition-all duration-150 p-4 group"
    >
      {renderContent(iconSlot)}
    </Link>
  );
}
