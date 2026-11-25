'use client';

import { useState, useRef, useEffect, type ReactNode } from 'react';
import { useAuthStore } from '@/store/useAuthStore';
import { api } from '@/lib/api';
import Link from 'next/link';
import { FolderIcon, GitBranchIcon, TriangleAlertIcon, CircleCheckIcon, MoveRightIcon } from '@animateicons/react/lucide';
import { timeAgo } from '@/components/shared/time-ago';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonCard, SkeletonList } from '@/components/shared/skeleton';
import { ErrorBanner } from '@/components/shared/error-banner';
import { SeverityRail } from '@/components/shared/severity-rail';
import { metricDisplay } from '@/lib/metric-display';
import { useQuery } from '@tanstack/react-query';

type IconHandle = { startAnimation: () => void; stopAnimation: () => void };

function StatCard({ label, value, icon: Icon, accent, sub }: { label: string; value: number | string; icon: React.ComponentType<{ ref?: React.Ref<IconHandle>; size?: number; isAnimated?: boolean }>; accent: string; sub?: ReactNode }) {
  const iconRef = useRef<IconHandle>(null);
  return (
    <div
      onMouseEnter={() => iconRef.current?.startAnimation()}
      onMouseLeave={() => iconRef.current?.stopAnimation()}
      className="cursor-target relative overflow-hidden rounded-xl border border-border bg-surface-1 p-4 transition-colors hover:border-brand/30"
    >
      <div className={`absolute top-0 left-0 right-0 h-[2px] ${accent}`} />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <p className="mt-2 text-3xl font-heading font-bold tracking-tight text-foreground">{value}</p>
          {sub && (
            <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">{sub}</p>
          )}
        </div>
        <div className="rounded-lg bg-white/[0.04] p-2 text-muted-foreground">
          <Icon ref={iconRef} size={18} isAnimated={false} />
        </div>
      </div>
    </div>
  );
}

function ViewAllLink() {
  const arrowRef = useRef<IconHandle>(null);
  return (
    <Link
      href="/reviews"
      onMouseEnter={() => arrowRef.current?.startAnimation()}
      onMouseLeave={() => arrowRef.current?.stopAnimation()}
      className="cursor-target text-sm text-brand hover:text-brand-hover flex items-center gap-1 transition-colors"
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

  const { data: stats, isLoading: statsLoading, error: statsError, dataUpdatedAt: statsUpdated, refetch: statsRefetch } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: api.getStats,
    refetchInterval: 5000,
  });

  const { data: reviews = [], isLoading: reviewsLoading, error: reviewsError, refetch: reviewsRefetch } = useQuery({
    queryKey: ['dashboard-reviews'],
    queryFn: () => api.getReviews(10),
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (!statsUpdated) return;
    const updateTime = () => setTimeText(timeAgo(new Date(statsUpdated).toISOString()));
    updateTime();
    const t = setInterval(updateTime, 10000);
    return () => clearInterval(t);
  }, [statsUpdated]);

  const hasActiveReviews = reviews.some((r) => r.status === 'running' || r.status === 'pending');
  const issuesCaughtValue = !stats
    ? '—'
    : stats.issues_caught_available
      ? stats.total_issues_caught
      : '—';
  const issuesCaughtSub = !stats || stats.issues_caught_available
    ? undefined
    : stats.issues_caught_reason ?? 'Findings data unavailable';

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-2xl md:text-3xl font-heading font-bold tracking-tight text-foreground">
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
        <ErrorBanner
          message="Failed to load some dashboard data."
          action={
            <button
              type="button"
              onClick={() => {
                void statsRefetch();
                void reviewsRefetch();
              }}
              className="cursor-pointer rounded-lg border border-error/30 px-3 py-1.5 text-xs font-medium text-error transition-colors hover:bg-error/10"
            >
              Retry
            </button>
          }
        />
      )}

      {/* Findings severity rail — the product's subject as the page's spine */}
      {stats?.issues_caught_available && (
        <SeverityRail
          className="mb-8"
          counts={{
            critical: stats.critical_count,
            high: stats.high_count,
            medium: stats.medium_count,
            low: stats.low_count,
            suggestions: stats.suggestions_count,
          }}
        />
      )}

      {/* Stat Cards */}
      {statsLoading ? (
        <SkeletonCard count={4} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatCard
            label="Connected repositories"
            value={metricDisplay(stats?.connected_repos)}
            accent="bg-info"
            icon={FolderIcon}
          />
          <StatCard
            label="PRs reviewed"
            value={metricDisplay(stats?.total_prs_reviewed)}
            accent="bg-brand"
            icon={GitBranchIcon}
          />
          <StatCard
            label="Issues caught"
            value={issuesCaughtValue}
            accent="bg-warning"
            icon={TriangleAlertIcon}
            sub={issuesCaughtSub}
          />
          <StatCard
            label="Completed reviews"
            value={metricDisplay(stats?.total_completed_reviews)}
            accent="bg-success"
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
              className="flex-1 min-w-0 h-10 px-4 py-2 bg-surface-1 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand/60 transition-colors"
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
