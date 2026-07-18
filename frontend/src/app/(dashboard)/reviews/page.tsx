'use client';

import { useState, useRef, useEffect } from 'react';
import { api } from '@/lib/api';
import { GitBranchIcon, TriangleAlertIcon, XIcon } from '@animateicons/react/lucide';
import { CalendarIcon } from 'lucide-react';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonList } from '@/components/shared/skeleton';
import { useQuery } from '@tanstack/react-query';
import { ReviewItem } from '@/components/shared/review-item';
import { DateRangeFilter } from '@/components/shared/date-range-filter';

const filterOptions = [
  { label: 'All', value: 'all' },
  { label: 'Running', value: 'running' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
  { label: 'Pending', value: 'pending' },
];

/* ─── Main Page ─── */
export default function ReviewsPage() {
  const [filter, setFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Date range state
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [fromTime, setFromTime] = useState('00:00');
  const [toTime, setToTime] = useState('23:59');
  const [useTime, setUseTime] = useState(false);
  const [showDateFilter, setShowDateFilter] = useState(false);

  const { data: reviews = [], isLoading, error } = useQuery({
    queryKey: ['reviews'],
    queryFn: () => api.getReviews(50),
    refetchInterval: 5000,
  });

  const clearDateFilter = () => {
    setFromDate(''); setToDate('');
    setFromTime('00:00'); setToTime('23:59');
    setUseTime(false);
  };

  const filteredReviews = reviews.filter((review) => {
    if (filter !== 'all' && review.status !== filter) return false;

    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const title = (review.pull_request?.title || '').toLowerCase();
      const repo = (review.repository?.full_name || '').toLowerCase();
      const author = (review.pull_request?.author || '').toLowerCase();
      if (!title.includes(q) && !repo.includes(q) && !author.includes(q)) return false;
    }

    // Date range filter
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

  const hasDateFilter = fromDate || toDate;

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="flex items-start justify-between mb-8 flex-wrap gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">Reviews</h1>
          <p className="text-muted-foreground mt-1 text-sm">All AI code reviews across your repositories.</p>
        </div>
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

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        {/* Search */}
        <div className="w-full sm:max-w-xs">
          <label htmlFor="review-search" className="sr-only">Search reviews</label>
          <input
            id="review-search"
            type="text"
            placeholder="Search by title, repo, author..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full h-10 px-4 py-2 bg-surface-1 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/50 transition-colors"
          />
        </div>

        {/* Status Filters */}
        <div className="flex items-center gap-2 overflow-x-auto pb-2 sm:pb-0 scrollbar-hide shrink-0">
          {filterOptions.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors cursor-pointer ${
                filter === opt.value
                  ? 'bg-foreground text-background shadow-sm'
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
          title={searchQuery || filter !== 'all' || hasDateFilter ? 'No matches found' : 'No reviews found'}
          description={
            searchQuery || filter !== 'all' || hasDateFilter
              ? 'Try adjusting your filters, date range, or search terms.'
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
            {hasDateFilter ? ' in selected date range' : ''}
          </p>
        </div>
      )}
    </div>
  );
}

