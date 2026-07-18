'use client';

import { useState, useRef, useEffect } from 'react';
import { useAuthStore } from '@/store/useAuthStore';
import { api, Review, DashboardStats } from '@/lib/api';
import Link from 'next/link';
import { FolderIcon, GitBranchIcon, TriangleAlertIcon, CircleCheckIcon, MessageCircleIcon, MoveRightIcon } from '@animateicons/react/lucide';
import { StatusBadge } from '@/components/shared/status-badge';
import { timeAgo, formatDateTimeWithRelative } from '@/components/shared/time-ago';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonCard, SkeletonList } from '@/components/shared/skeleton';
import { useQuery } from '@tanstack/react-query';

function StatCard({ label, value, icon: Icon, accent }: { label: string; value: number | string; icon: any; accent: string }) {
  const iconRef = useRef<any>(null);
  return (
    <div
      onMouseEnter={() => iconRef.current?.startAnimation()}
      onMouseLeave={() => iconRef.current?.stopAnimation()}
      className="relative overflow-hidden rounded-xl border border-border bg-surface-1 p-4 transition-colors hover:border-white/[0.08]"
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

import { ReviewItem } from '@/components/shared/review-item';


export default function Dashboard() {
  const { user } = useAuthStore();
  const [searchQuery, setSearchQuery] = useState('');
  const [timeText, setTimeText] = useState('just now');

  const { data: stats, isLoading: statsLoading, error: statsError, dataUpdatedAt: statsUpdated } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: api.getStats,
    refetchInterval: 5000,
  });

  const { data: reviews = [], isLoading: reviewsLoading, error: reviewsError } = useQuery({
    queryKey: ['dashboard-reviews'],
    queryFn: () => api.getReviews(10),
    refetchInterval: 5000,
  });

  const loading = statsLoading || reviewsLoading;

  useEffect(() => {
    if (!statsUpdated) return;
    const updateTime = () => setTimeText(timeAgo(new Date(statsUpdated).toISOString()));
    updateTime();
    const t = setInterval(updateTime, 10000);
    return () => clearInterval(t);
  }, [statsUpdated]);

  const hasActiveReviews = reviews.some((r) => r.status === 'running' || r.status === 'pending');

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
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

      {(statsError || reviewsError) && (
        <div className="mb-6 p-4 bg-error/10 border border-error/20 rounded-lg flex items-center gap-3">
          <TriangleAlertIcon size={20} className="text-error" />
          <p className="text-sm text-error">Failed to load some dashboard data. Retrying...</p>
        </div>
      )}

      {/* Stat Cards */}
      {statsLoading ? (
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
            <label htmlFor="dashboard-search" className="sr-only">Search reviews</label>
            <input
              id="dashboard-search"
              type="text"
              placeholder="Search reviews by PR title, repo, or author..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="flex-1 min-w-0 h-10 px-4 py-2 bg-surface-1 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/50 transition-colors"
            />
            <ViewAllLink />
          </div>
        </div>

        {reviewsLoading ? (
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
