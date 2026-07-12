'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { api, Review } from '@/lib/api';
import Link from 'next/link';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { CircleCheckIcon, TriangleAlertIcon, ClipboardIcon, MoveRightIcon } from '@animateicons/react/lucide';
import { StatusBadge } from '@/components/shared/status-badge';
import { timeAgo } from '@/components/shared/time-ago';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonList } from '@/components/shared/skeleton';

function ReviewListItem({ review }: { review: Review }) {
  const statusRef = useRef<any>(null);
  const arrowRef = useRef<any>(null);

  const pr = review.pull_request;
  const repo = review.repository;
  const duration =
    review.started_at && review.completed_at
      ? Math.round((new Date(review.completed_at).getTime() - new Date(review.started_at).getTime()) / 1000)
      : null;

  return (
    <Link
      href={`/reviews/${review.id}`}
      onMouseEnter={() => {
        statusRef.current?.startAnimation?.();
        arrowRef.current?.startAnimation?.();
      }}
      onMouseLeave={() => {
        statusRef.current?.stopAnimation?.();
        arrowRef.current?.stopAnimation?.();
      }}
      className="block rounded-xl border border-border bg-surface-1 hover:border-brand/30 transition-all duration-150 p-4 group"
    >
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div className="w-9 h-9 rounded-lg bg-white/[0.04] flex items-center justify-center text-muted-foreground group-hover:text-brand transition-colors shrink-0">
          {review.status === 'running' ? (
            <LoaderIcon size={18} className="text-brand" />
          ) : review.status === 'completed' ? (
            <CircleCheckIcon ref={statusRef} size={18} isAnimated={false} className="text-success" />
          ) : review.status === 'failed' ? (
            <TriangleAlertIcon ref={statusRef} size={18} isAnimated={false} className="text-error" />
          ) : (
            <ClipboardIcon ref={statusRef} size={18} isAnimated={false} />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <span className="font-semibold text-foreground truncate text-sm">{pr?.title ?? 'Pull Request'}</span>
            <StatusBadge status={review.status} />
          </div>
          <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground flex-wrap">
            <span className="text-brand/80">{repo?.full_name}</span>
            <span className="text-border">·</span>
            <span>PR #{pr?.pr_number}</span>
            {pr?.author && <><span className="text-border">·</span><span>@{pr.author}</span></>}
            {pr?.additions !== undefined && (
              <>
                <span className="text-border">·</span>
                <span className="text-success">+{pr.additions}</span>
                <span className="text-error">-{pr.deletions}</span>
                <span>({pr.changed_files} files)</span>
              </>
            )}
          </div>
          {review.status === 'failed' && review.error_message && (
            <div className="mt-2 p-2.5 bg-error/5 border border-error/20 rounded-lg text-xs font-mono text-error/90 whitespace-pre-wrap break-all">
              {review.error_message}
            </div>
          )}
        </div>

        {/* Meta */}
        <div className="text-right shrink-0">
          <div className="text-xs text-muted-foreground">{timeAgo(review.created_at)}</div>
          {duration !== null && (
            <div className="text-xs text-border mt-0.5">{duration}s</div>
          )}
          <MoveRightIcon ref={arrowRef} size={16} isAnimated={false} className="text-border group-hover:text-brand transition-colors ml-auto mt-2" />
        </div>
      </div>
    </Link>
  );
}

export default function ReviewsPage() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');

  const fetchReviews = useCallback(async () => {
    try {
      const data = await api.getReviews(50);
      setReviews(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchReviews();
    const interval = setInterval(fetchReviews, 10_000);
    return () => clearInterval(interval);
  }, [fetchReviews]);

  const filtered = filter === 'all' ? reviews : reviews.filter((r) => r.status === filter);
  const hasActive = reviews.some((r) => r.status === 'running' || r.status === 'pending');

  const tabs = ['all', 'running', 'completed', 'failed', 'pending'];

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">Reviews</h1>
          <p className="text-muted-foreground mt-1 text-sm">All AI code reviews across your repositories.</p>
        </div>
        {hasActive && (
          <div className="flex items-center gap-2 text-sm text-info border border-info/20 bg-info/5 px-3 py-1.5 rounded-lg">
            <span className="w-1.5 h-1.5 rounded-full bg-info animate-pulse" />
            Review in progress...
          </div>
        )}
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-1 mb-5 border-b border-border pb-3 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setFilter(tab)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium capitalize transition-all duration-150 whitespace-nowrap ${
              filter === tab
                ? 'bg-brand/15 text-brand'
                : 'text-muted-foreground hover:text-foreground hover:bg-white/[0.04]'
            }`}
          >
            {tab}
            {tab !== 'all' && (
              <span className="ml-1.5 text-xs opacity-60">
                ({reviews.filter((r) => r.status === tab).length})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Reviews List */}
      {loading ? (
        <SkeletonList count={5} height="h-20" />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<ClipboardIcon size={28} />}
          title="No reviews found"
          description={
            filter === 'all'
              ? 'Open a Pull Request to trigger your first AI review.'
              : `No ${filter} reviews.`
          }
        />
      ) : (
        <div className="space-y-2">
          {filtered.map((review) => (
            <ReviewListItem key={review.id} review={review} />
          ))}
        </div>
      )}
    </div>
  );
}
