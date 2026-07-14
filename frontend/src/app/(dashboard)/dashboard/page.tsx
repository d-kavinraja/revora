'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useAuthStore } from '@/store/useAuthStore';
import { api, Review, DashboardStats } from '@/lib/api';
import Link from 'next/link';
import { FolderIcon, GitBranchIcon, TriangleAlertIcon, CircleCheckIcon, MessageCircleIcon, MoveRightIcon } from '@animateicons/react/lucide';
import { StatusBadge } from '@/components/shared/status-badge';
import { timeAgo, formatDateTimeWithRelative } from '@/components/shared/time-ago';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonCard, SkeletonList } from '@/components/shared/skeleton';

function StatCard({ label, value, icon: Icon, accent }: { label: string; value: number | string; icon: any; accent: string }) {
  const iconRef = useRef<any>(null);
  return (
    <div
      onMouseEnter={() => iconRef.current?.startAnimation()}
      onMouseLeave={() => iconRef.current?.stopAnimation()}
      className="relative overflow-hidden rounded-xl border border-border bg-surface-1 p-5 transition-colors hover:border-white/[0.08]"
    >
      <div className={`absolute top-0 left-0 right-0 h-[2px] ${accent}`} />
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-muted-foreground tracking-wide uppercase">{label}</p>
          <p className="mt-2 text-3xl font-bold tracking-tight text-foreground">{value}</p>
        </div>
        <div className="rounded-lg bg-white/[0.04] p-2 text-muted-foreground">
          <Icon ref={iconRef} size={18} isAnimated={false} />
        </div>
      </div>
    </div>
  );
}

function ViewAllLink() {
  const arrowRef = useRef<any>(null);
  return (
    <Link
      href="/reviews"
      onMouseEnter={() => arrowRef.current?.startAnimation()}
      onMouseLeave={() => arrowRef.current?.stopAnimation()}
      className="text-sm text-brand hover:text-brand-hover flex items-center gap-1 transition-colors"
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
      className="block rounded-xl border border-border bg-surface-1 hover:border-brand/30 transition-all duration-150 p-4 group"
    >
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
          <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground flex-wrap">
            <span className="text-brand/80">{review.repository?.full_name}</span>
            <span className="text-border">·</span>
            <span>PR #{review.pull_request?.pr_number}</span>
            <span className="text-border">·</span>
            <span>@{review.pull_request?.author}</span>
            <span className="text-border">·</span>
            <span>{formatDateTimeWithRelative(review.created_at)}</span>
          </div>
          {review.status === 'failed' && review.error_message && (
            <div className="mt-2 p-2.5 bg-error/5 border border-error/20 rounded-lg text-xs font-mono text-error/90 whitespace-pre-wrap break-all">
              {review.error_message}
            </div>
          )}
        </div>
        <MoveRightIcon ref={arrowRef} size={16} isAnimated={false} className="text-border group-hover:text-brand transition-colors shrink-0 mt-2" />
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
  const [timeText, setTimeText] = useState('0s ago');
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    setTimeText(timeAgo(lastRefresh.toISOString()));
    const t = setInterval(() => {
      setTimeText(timeAgo(lastRefresh.toISOString()));
    }, 1000);
    return () => clearInterval(t);
  }, [lastRefresh]);

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
    const interval = setInterval(fetchData, 3_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const hasActiveReviews = reviews.some((r) => r.status === 'running' || r.status === 'pending');

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
            Welcome back, {user?.name?.split(' ')[0]}
          </h1>
          <p className="mt-1 text-muted-foreground">
            Here&apos;s what&apos;s happening with your code reviews.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
          {hasActiveReviews && (
            <span className="flex items-center gap-1.5 text-info">
              <span className="w-1.5 h-1.5 rounded-full bg-info animate-pulse" />
              Live
            </span>
          )}
          <span>Updated {timeText}</span>
        </div>
      </div>

      {/* Stat Cards */}
      {loading ? (
        <SkeletonCard count={4} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatCard
            label="Connected Repos"
            value={stats?.connected_repos ?? 0}
            accent="bg-gradient-to-r from-blue-500 to-cyan-500"
            icon={FolderIcon}
          />
          <StatCard
            label="PRs Reviewed"
            value={stats?.total_prs_reviewed ?? 0}
            accent="bg-gradient-to-r from-brand to-purple-500"
            icon={GitBranchIcon}
          />
          <StatCard
            label="Issues Caught"
            value={stats?.total_issues_caught ?? 0}
            accent="bg-gradient-to-r from-warning to-amber-500"
            icon={TriangleAlertIcon}
          />
          <StatCard
            label="Completed Reviews"
            value={stats?.total_completed_reviews ?? 0}
            accent="bg-gradient-to-r from-success to-emerald-500"
            icon={CircleCheckIcon}
          />
        </div>
      )}

      {/* Recent Reviews */}
      <div>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
          <h2 className="text-lg font-bold text-foreground">Recent Reviews</h2>
          <div className="flex items-center gap-3 flex-1 sm:max-w-md w-full">
            <input
              type="text"
              placeholder="Search reviews by PR title, repo, or author..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="flex-1 min-w-0 px-3 py-1.5 bg-surface-1 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/50 transition-colors"
            />
            <ViewAllLink />
          </div>
        </div>

        {loading ? (
          <SkeletonList count={3} />
        ) : reviews.length === 0 ? (
          <EmptyState
            icon={<GitBranchIcon size={28} />}
            title="No reviews yet"
            description="Open a Pull Request to trigger your first AI review."
          />
        ) : (
          (() => {
            const filteredReviews = reviews.filter((review) => {
              const query = searchQuery.toLowerCase();
              const title = (review.pull_request?.title || '').toLowerCase();
              const repoName = (review.repository?.full_name || '').toLowerCase();
              const author = (review.pull_request?.author || '').toLowerCase();
              return title.includes(query) || repoName.includes(query) || author.includes(query);
            });

            if (filteredReviews.length === 0) {
              return (
                <EmptyState
                  icon={<GitBranchIcon size={28} />}
                  title="No matching reviews"
                  description="Try adjusting your search terms."
                />
              );
            }

            return (
              <div className="space-y-2">
                {filteredReviews.map((review) => (
                  <ReviewItem key={review.id} review={review} />
                ))}
              </div>
            );
          })()
        )}
      </div>
    </div>
  );
}
