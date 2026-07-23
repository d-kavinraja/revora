'use client';

import { useState, useMemo } from 'react';
import { api } from '@/lib/api';
import { GitBranchIcon, TriangleAlertIcon } from '@animateicons/react/lucide';
import { CalendarIcon, FolderGit2, GitPullRequest, RotateCcw } from 'lucide-react';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonList } from '@/components/shared/skeleton';
import { useQuery } from '@tanstack/react-query';
import { ReviewItem } from '@/components/shared/review-item';
import { DateRangeFilter } from '@/components/shared/date-range-filter';

const filterOptions = [
  { label: 'All Statuses', value: 'all' },
  { label: 'Running', value: 'running' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
  { label: 'Pending', value: 'pending' },
];

/* ─── Main Page ─── */
export default function ReviewsPage() {
  const [filter, setFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRepo, setSelectedRepo] = useState<string>('all');
  const [selectedPR, setSelectedPR] = useState<string>('all');

  // Date range state
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [fromTime, setFromTime] = useState('00:00');
  const [toTime, setToTime] = useState('23:59');
  const [useTime, setUseTime] = useState(false);
  const [showDateFilter, setShowDateFilter] = useState(false);

  // Fetch reviews
  const { data: reviews = [], isLoading, error } = useQuery({
    queryKey: ['reviews'],
    queryFn: () => api.getReviews(100),
    refetchInterval: 5000,
  });

  // Fetch connected repositories
  const { data: repositories = [] } = useQuery({
    queryKey: ['repositories'],
    queryFn: () => api.getRepositories(),
  });

  // Build Connected Repowise options
  const repoOptions = useMemo(() => {
    const repoMap = new Map<string, string>();
    repositories.forEach((repo) => {
      if (repo.full_name) {
        repoMap.set(repo.full_name, repo.full_name);
      }
    });
    reviews.forEach((review) => {
      if (review.repository?.full_name) {
        repoMap.set(review.repository.full_name, review.repository.full_name);
      }
    });
    return Array.from(repoMap.values()).sort();
  }, [repositories, reviews]);

  // Build Pull Request Wise options (filtered by selectedRepo if active)
  const prOptions = useMemo(() => {
    const prMap = new Map<string, { pr_number: number; title: string; repo: string }>();
    reviews.forEach((review) => {
      if (review.pull_request) {
        const repoName = review.repository?.full_name || '';
        if (selectedRepo !== 'all' && repoName !== selectedRepo) {
          return;
        }
        const prKey = `${repoName}#${review.pull_request.pr_number}`;
        if (!prMap.has(prKey)) {
          prMap.set(prKey, {
            pr_number: review.pull_request.pr_number,
            title: review.pull_request.title || 'Untitled PR',
            repo: repoName,
          });
        }
      }
    });

    return Array.from(prMap.values()).sort((a, b) => b.pr_number - a.pr_number);
  }, [reviews, selectedRepo]);

  const clearDateFilter = () => {
    setFromDate(''); setToDate('');
    setFromTime('00:00'); setToTime('23:59');
    setUseTime(false);
  };

  const clearAllFilters = () => {
    setFilter('all');
    setSearchQuery('');
    setSelectedRepo('all');
    setSelectedPR('all');
    clearDateFilter();
  };

  const filteredReviews = reviews.filter((review) => {
    // 1. Status Filter
    if (filter !== 'all' && review.status !== filter) return false;

    // 2. Search Query Filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const title = (review.pull_request?.title || '').toLowerCase();
      const repo = (review.repository?.full_name || '').toLowerCase();
      const author = (review.pull_request?.author || '').toLowerCase();
      const prNum = `#${review.pull_request?.pr_number || ''}`;
      if (!title.includes(q) && !repo.includes(q) && !author.includes(q) && !prNum.includes(q)) return false;
    }

    // 3. Connected Repowise Filter
    if (selectedRepo !== 'all') {
      const repoFullName = review.repository?.full_name || '';
      const repoName = review.repository?.name || '';
      if (repoFullName !== selectedRepo && repoName !== selectedRepo) return false;
    }

    // 4. Pull Request Wise Filter
    if (selectedPR !== 'all') {
      if (String(review.pull_request?.pr_number) !== String(selectedPR)) return false;
    }

    // 5. Date Range Filter
    if (fromDate) {
      const reviewDate = new Date(review.created_at ?? '');
      const startStr = useTime && fromTime ? `${fromDate}T${fromTime}:00` : `${fromDate}T00:00:00`;
      if (reviewDate < new Date(startStr)) return false;
    }
    if (toDate) {
      const reviewDate = new Date(review.created_at ?? '');
      const endStr = useTime && toTime ? `${toDate}T${toTime}:59` : `${toDate}T23:59:59`;
      if (reviewDate > new Date(endStr)) return false;
    }

    return true;
  });

  const hasDateFilter = Boolean(fromDate || toDate);
  const hasActiveFilters = Boolean(
    filter !== 'all' ||
    searchQuery !== '' ||
    selectedRepo !== 'all' ||
    selectedPR !== 'all' ||
    hasDateFilter
  );

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      {/* Header Bar */}
      <div className="flex items-start justify-between mb-8 flex-wrap gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">Reviews</h1>
          <p className="text-muted-foreground mt-1 text-sm">All AI code reviews across your connected repositories.</p>
        </div>
        <div className="flex items-center gap-2">
          {hasActiveFilters && (
            <button
              onClick={clearAllFilters}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-surface-1 border border-border text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors cursor-pointer"
            >
              <RotateCcw size={13} />
              Reset Filters
            </button>
          )}
          {/* Calendar toggle button */}
          <button
            onClick={() => setShowDateFilter(o => !o)}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium border transition-colors cursor-pointer ${
              showDateFilter || hasDateFilter
                ? 'bg-brand/10 border-brand/30 text-brand'
                : 'bg-surface-1 border-border text-muted-foreground hover:text-foreground hover:bg-white/[0.04]'
            }`}
          >
            <CalendarIcon size={15} />
            Date Filter
            {hasDateFilter && (
              <span className="ml-1 w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
            )}
          </button>
        </div>
      </div>

      {/* Date Range Filter Panel */}
      {showDateFilter && (
        <DateRangeFilter
          fromDate={fromDate} toDate={toDate}
          fromTime={fromTime} toTime={toTime}
          useTime={useTime}
          onFromDate={setFromDate} onToDate={setToDate}
          onFromTime={setFromTime} onToTime={setToTime}
          onToggleTime={() => setUseTime(u => !u)}
          onClear={clearDateFilter}
        />
      )}

      {/* Primary Filter Controls Bar */}
      <div className="space-y-3 mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* Search Input */}
          <div className="w-full">
            <label htmlFor="review-search" className="sr-only">Search reviews</label>
            <input
              id="review-search"
              type="text"
              placeholder="Search by title, repo, author..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full h-10 px-3.5 py-2 bg-surface-1 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/50 transition-colors"
            />
          </div>

          {/* Connected Repowise Filter */}
          <div className="relative w-full">
            <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none text-muted-foreground">
              <FolderGit2 size={15} />
            </div>
            <select
              value={selectedRepo}
              onChange={(e) => {
                setSelectedRepo(e.target.value);
                setSelectedPR('all');
              }}
              className={`w-full h-10 pl-9 pr-8 bg-surface-1 border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 transition-colors appearance-none cursor-pointer ${
                selectedRepo !== 'all' ? 'border-brand/50 text-brand bg-brand/5 font-medium' : 'border-border'
              }`}
            >
              <option value="all">All Connected Repositories</option>
              {repoOptions.map((repo) => (
                <option key={repo} value={repo}>
                  {repo}
                </option>
              ))}
            </select>
            <div className="absolute inset-y-0 right-3 flex items-center pointer-events-none text-muted-foreground text-xs">
              ▼
            </div>
          </div>

          {/* Pull Request Wise Filter */}
          <div className="relative w-full">
            <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none text-muted-foreground">
              <GitPullRequest size={15} />
            </div>
            <select
              value={selectedPR}
              onChange={(e) => setSelectedPR(e.target.value)}
              className={`w-full h-10 pl-9 pr-8 bg-surface-1 border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 transition-colors appearance-none cursor-pointer ${
                selectedPR !== 'all' ? 'border-brand/50 text-brand bg-brand/5 font-medium' : 'border-border'
              }`}
            >
              <option value="all">
                {selectedRepo !== 'all' ? 'All PRs in Repo' : 'All Pull Requests'}
              </option>
              {prOptions.map((pr) => (
                <option key={`${pr.repo}#${pr.pr_number}`} value={String(pr.pr_number)}>
                  PR #{pr.pr_number}: {pr.title.length > 28 ? `${pr.title.slice(0, 28)}...` : pr.title}
                </option>
              ))}
            </select>
            <div className="absolute inset-y-0 right-3 flex items-center pointer-events-none text-muted-foreground text-xs">
              ▼
            </div>
          </div>

          {/* Status Filter Dropdown */}
          <div className="hidden lg:block w-full">
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className={`w-full h-10 px-3.5 bg-surface-1 border rounded-lg text-sm focus:outline-none focus:border-brand/50 transition-colors cursor-pointer appearance-none ${
                filter !== 'all' ? 'border-brand/50 text-brand bg-brand/5 font-medium' : 'border-border text-foreground'
              }`}
            >
              {filterOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Status Filter Pills Bar */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-hide pt-1">
          <span className="text-xs text-muted-foreground font-medium mr-1 hidden sm:inline">Status:</span>
          {filterOptions.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors cursor-pointer ${
                filter === opt.value
                  ? 'bg-foreground text-background shadow-sm font-semibold'
                  : 'bg-surface-1 border border-border text-muted-foreground hover:text-foreground hover:bg-white/[0.04]'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-error/10 border border-error/20 rounded-lg flex items-center gap-3">
          <TriangleAlertIcon size={20} className="text-error" />
          <p className="text-sm text-error">Failed to load reviews. Retrying...</p>
        </div>
      )}

      {isLoading ? (
        <SkeletonList count={5} />
      ) : filteredReviews.length === 0 ? (
        <EmptyState
          icon={<GitBranchIcon size={32} />}
          title={hasActiveFilters ? 'No matching reviews' : 'No reviews found'}
          description={
            hasActiveFilters
              ? 'Try adjusting or resetting your repo, PR, status, or date range filters.'
              : 'Pull request reviews will appear here once your repositories are active.'
          }
        />
      ) : (
        <div className="space-y-2.5">
          {filteredReviews.map((review) => (
            <ReviewItem key={review.id} review={review} />
          ))}
          <p className="text-center text-xs text-muted-foreground pt-2">
            {filteredReviews.length} review{filteredReviews.length !== 1 ? 's' : ''} shown
            {selectedRepo !== 'all' ? ` for ${selectedRepo}` : ''}
            {selectedPR !== 'all' ? ` (PR #${selectedPR})` : ''}
            {hasDateFilter ? ' in selected date range' : ''}
          </p>
        </div>
      )}
    </div>
  );
}

