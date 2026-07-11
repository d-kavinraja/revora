'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { api, Review } from '@/lib/api';
import Link from 'next/link';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { CircleCheckIcon, TriangleAlertIcon, ClipboardIcon, MoveRightIcon } from '@animateicons/react/lucide';

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; dot: string }> = {
    pending:   { label: 'Pending',   cls: 'bg-yellow-500/10 text-yellow-300 border-yellow-500/30',   dot: 'bg-yellow-400' },
    running:   { label: 'Running',   cls: 'bg-blue-500/10   text-blue-300   border-blue-500/30',     dot: 'bg-blue-400 animate-pulse' },
    completed: { label: 'Completed', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30', dot: 'bg-emerald-400' },
    failed:    { label: 'Failed',    cls: 'bg-red-500/10    text-red-300    border-red-500/30',       dot: 'bg-red-400' },
  };
  const s = map[status] ?? { label: status, cls: 'bg-zinc-800 text-zinc-400 border-zinc-700', dot: 'bg-zinc-500' };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${s.cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return '';
  const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

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
      className="block rounded-xl border border-white/5 bg-zinc-950 hover:border-indigo-500/30 hover:bg-zinc-950/80 transition-all duration-200 p-5 group"
    >
      <div className="flex items-start gap-4">
        {/* Icon */}
        <div className="w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center text-zinc-400 group-hover:text-indigo-400 transition-colors shrink-0">
          {review.status === 'running' ? (
            <LoaderIcon size={20} className="text-indigo-400" />
          ) : review.status === 'completed' ? (
            <CircleCheckIcon ref={statusRef} size={20} isAnimated={false} className="text-emerald-400" />
          ) : review.status === 'failed' ? (
            <TriangleAlertIcon ref={statusRef} size={20} isAnimated={false} className="text-red-400" />
          ) : (
            <ClipboardIcon ref={statusRef} size={20} isAnimated={false} />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="font-semibold text-white truncate">{pr?.title ?? 'Pull Request'}</span>
            <StatusBadge status={review.status} />
          </div>
          <div className="flex items-center gap-3 mt-1.5 text-xs text-zinc-500 flex-wrap">
            <span className="text-indigo-400/80">{repo?.full_name}</span>
            <span>·</span>
            <span>PR #{pr?.pr_number}</span>
            {pr?.author && <><span>·</span><span>@{pr.author}</span></>}
            {pr?.additions !== undefined && (
              <>
                <span>·</span>
                <span className="text-emerald-500">+{pr.additions}</span>
                <span className="text-red-500">-{pr.deletions}</span>
                <span>({pr.changed_files} files)</span>
              </>
            )}
          </div>
          {review.status === 'failed' && review.error_message && (
            <p className="mt-1.5 text-xs text-red-400 truncate max-w-xl">{review.error_message}</p>
          )}
        </div>

        {/* Meta */}
        <div className="text-right shrink-0">
          <div className="text-xs text-zinc-500">{timeAgo(review.created_at)}</div>
          {duration !== null && (
            <div className="text-xs text-zinc-600 mt-0.5">{duration}s</div>
          )}
          <MoveRightIcon ref={arrowRef} size={16} isAnimated={false} className="text-zinc-600 group-hover:text-indigo-400 transition-colors ml-auto mt-2" />
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

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Reviews</h1>
          <p className="text-zinc-400 mt-1.5">All AI code reviews across your repositories.</p>
        </div>
        {hasActive && (
          <div className="flex items-center gap-2 text-sm text-blue-400 mt-1 border border-blue-500/20 bg-blue-500/5 px-3 py-1.5 rounded-lg">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            Review in progress...
          </div>
        )}
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 mb-6 border-b border-white/5 pb-4">
        {['all', 'running', 'completed', 'failed', 'pending'].map((tab) => (
          <button
            key={tab}
            onClick={() => setFilter(tab)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium capitalize transition-all duration-150 ${
              filter === tab
                ? 'bg-indigo-500/15 text-indigo-300'
                : 'text-zinc-500 hover:text-zinc-300 hover:bg-white/5'
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
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-24 rounded-xl bg-zinc-950 border border-white/5 animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/10 p-16 text-center">
          <p className="text-zinc-400 font-medium">No reviews found</p>
          <p className="text-zinc-600 text-sm mt-1">
            {filter === 'all' ? 'Open a Pull Request to trigger your first AI review.' : `No ${filter} reviews.`}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((review) => (
            <ReviewListItem key={review.id} review={review} />
          ))}
        </div>
      )}
    </div>
  );
}
