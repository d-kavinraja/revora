'use client';

import { useRef } from 'react';
import Link from 'next/link';
import { MessageCircleIcon, MoveRightIcon } from '@animateicons/react/lucide';
import { ProviderIcon } from '@/components/ui/provider-icon';
import BorderGlow from '@/components/ui/BorderGlow';
import { StatusBadge } from '@/components/shared/status-badge';
import { formatDateTimeWithRelative } from '@/components/shared/time-ago';
import { Review } from '@/lib/api';

export function ReviewItem({ review }: { review: Review }) {
  const iconRef = useRef<any>(null);
  const arrowRef = useRef<any>(null);
  const content = (
    <div className="flex items-start gap-3">
      <div className="shrink-0">
        <div className="w-9 h-9 rounded-lg bg-white/[0.04] flex items-center justify-center text-muted-foreground group-hover:text-brand transition-colors">
          <MessageCircleIcon ref={iconRef} size={16} isAnimated={false} />
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className="font-semibold text-foreground truncate text-sm">
            {review.pull_request?.title ?? 'Pull Request'}
          </span>
          <StatusBadge status={review.status} />
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
          {content}
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
      {content}
    </Link>
  );
}
