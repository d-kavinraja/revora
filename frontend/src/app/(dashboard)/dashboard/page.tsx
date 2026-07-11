'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useAuthStore } from '@/store/useAuthStore';
import { api, Review, DashboardStats } from '@/lib/api';
import Link from 'next/link';
import { FolderIcon, GitBranchIcon, TriangleAlertIcon, CircleCheckIcon, MessageCircleIcon, MoveRightIcon } from '@animateicons/react/lucide';

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; dot: string }> = {
    pending:   { label: 'Pending',   cls: 'bg-yellow-500/10 text-yellow-300 border-yellow-500/30',  dot: 'bg-yellow-400' },
    running:   { label: 'Running',   cls: 'bg-blue-500/10   text-blue-300   border-blue-500/30',    dot: 'bg-blue-400 animate-pulse' },
    completed: { label: 'Completed', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30', dot: 'bg-emerald-400' },
    failed:    { label: 'Failed',    cls: 'bg-red-500/10    text-red-300    border-red-500/30',      dot: 'bg-red-400' },
  };
  const s = map[status] ?? { label: status, cls: 'bg-zinc-800 text-zinc-400 border-zinc-700', dot: 'bg-zinc-500' };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${s.cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

function StatCard({ label, value, icon: Icon, gradient }: { label: string; value: number | string; icon: any; gradient?: string }) {
  const iconRef = useRef<any>(null);
  return (
    <div
      onMouseEnter={() => iconRef.current?.startAnimation()}
      onMouseLeave={() => iconRef.current?.stopAnimation()}
      className="relative overflow-hidden rounded-2xl border border-white/5 bg-zinc-950 p-6 shadow-xl"
    >
      {gradient && <div className={`absolute inset-0 opacity-5 ${gradient}`} />}
      <div className="relative flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-zinc-400">{label}</p>
          <p className="mt-2 text-4xl font-bold tracking-tight text-white">{value}</p>
        </div>
        <div className="rounded-xl bg-white/5 p-2.5 text-zinc-400">
          <Icon ref={iconRef} size={20} isAnimated={false} />
        </div>
      </div>
    </div>
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

function ViewAllLink() {
  const arrowRef = useRef<any>(null);
  return (
    <Link
      href="/reviews"
      onMouseEnter={() => arrowRef.current?.startAnimation()}
      onMouseLeave={() => arrowRef.current?.stopAnimation()}
      className="text-sm text-indigo-400 hover:text-indigo-300 flex items-center gap-1 transition-colors"
    >
      View all
      <MoveRightIcon ref={arrowRef} size={16} isAnimated={false} />
    </Link>
  );
}

function ReviewItem({ review }: { review: Review }) {
  const iconRef = useRef<any>(null);
  const arrowRef = useRef<any>(null);
  return (
    <Link
      href={`/reviews/${review.id}`}
      onMouseEnter={() => {
        iconRef.current?.startAnimation();
        arrowRef.current?.startAnimation();
      }}
      onMouseLeave={() => {
        iconRef.current?.stopAnimation();
        arrowRef.current?.stopAnimation();
      }}
      className="block rounded-xl border border-white/5 bg-zinc-950 hover:border-indigo-500/30 hover:bg-zinc-950/80 transition-all duration-200 p-5 group"
    >
      <div className="flex items-start gap-4">
        <div className="mt-0.5 shrink-0">
          <div className="w-9 h-9 rounded-lg bg-white/5 flex items-center justify-center text-zinc-400 group-hover:text-indigo-400 transition-colors">
            <MessageCircleIcon ref={iconRef} size={16} isAnimated={false} />
          </div>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="font-semibold text-white truncate">
              {review.pull_request?.title ?? 'Pull Request'}
            </span>
            <StatusBadge status={review.status} />
          </div>
          <div className="flex items-center gap-3 mt-1.5 text-xs text-zinc-500 flex-wrap">
            <span className="text-indigo-400/80">{review.repository?.full_name}</span>
            <span>·</span>
            <span>PR #{review.pull_request?.pr_number}</span>
            <span>·</span>
            <span>by @{review.pull_request?.author}</span>
            <span>·</span>
            <span>{timeAgo(review.created_at)}</span>
          </div>
        </div>
        <MoveRightIcon ref={arrowRef} size={16} isAnimated={false} className="text-zinc-600 group-hover:text-indigo-400 transition-colors shrink-0 mt-2" />
      </div>
    </Link>
  );
}

export default function Dashboard() {
  const { user } = useAuthStore();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchData = useCallback(async () => {
    try {
      const [statsData, reviewsData] = await Promise.all([
        api.getStats(),
        api.getReviews(10),
      ]);
      setStats(statsData);
      setReviews(reviewsData);
      setLastRefresh(new Date());
    } catch (err) {
      console.error('Failed to load dashboard data', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const hasActiveReviews = reviews.some((r) => r.status === 'running' || r.status === 'pending');

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-10">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Welcome back, {user?.name?.split(' ')[0]} 👋
          </h1>
          <p className="mt-1.5 text-zinc-400">
            Here's what's happening with your code reviews.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-500 mt-1">
          {hasActiveReviews && (
            <span className="flex items-center gap-1.5 text-blue-400">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
              Live
            </span>
          )}
          <span>Last updated {timeAgo(lastRefresh.toISOString())}</span>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-10">
        <StatCard
          label="Connected Repos"
          value={loading ? '...' : stats?.connected_repos ?? 0}
          gradient="bg-gradient-to-br from-indigo-500 to-blue-600"
          icon={FolderIcon}
        />
        <StatCard
          label="PRs Reviewed"
          value={loading ? '...' : stats?.total_prs_reviewed ?? 0}
          gradient="bg-gradient-to-br from-purple-500 to-indigo-600"
          icon={GitBranchIcon}
        />
        <StatCard
          label="Issues Caught"
          value={loading ? '...' : stats?.total_issues_caught ?? 0}
          gradient="bg-gradient-to-br from-amber-500 to-orange-600"
          icon={TriangleAlertIcon}
        />
        <StatCard
          label="Completed Reviews"
          value={loading ? '...' : stats?.total_completed_reviews ?? 0}
          gradient="bg-gradient-to-br from-emerald-500 to-teal-600"
          icon={CircleCheckIcon}
        />
      </div>

      {/* Recent Reviews */}
      <div>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-xl font-bold text-white">Recent Reviews</h2>
          <ViewAllLink />
        </div>

        {loading ? (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-20 rounded-xl bg-zinc-950 border border-white/5 animate-pulse" />
            ))}
          </div>
        ) : reviews.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 p-16 text-center">
            <div className="w-14 h-14 rounded-full bg-zinc-900 flex items-center justify-center mx-auto mb-4">
              <GitBranchIcon size={28} className="text-zinc-600" />
            </div>
            <p className="text-zinc-400 font-medium">No reviews yet</p>
            <p className="text-zinc-600 text-sm mt-1">Open a Pull Request to trigger your first AI review.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {reviews.map((review) => (
              <ReviewItem key={review.id} review={review} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
