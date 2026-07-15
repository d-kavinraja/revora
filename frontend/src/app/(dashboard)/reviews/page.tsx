'use client';

import { useState, useRef, useEffect } from 'react';
import { api } from '@/lib/api';
import { GitBranchIcon, TriangleAlertIcon, XIcon } from '@animateicons/react/lucide';
import { CalendarIcon } from 'lucide-react';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonList } from '@/components/shared/skeleton';
import { useQuery } from '@tanstack/react-query';
import { ReviewItem } from '@/components/shared/review-item';

const filterOptions = [
  { label: 'All', value: 'all' },
  { label: 'Running', value: 'running' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
  { label: 'Pending', value: 'pending' },
];

/* ─── Mini Calendar Picker ─── */
function CalendarPicker({
  value,
  onChange,
  label,
  minDate,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  minDate?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Build the month grid
  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth()); // 0-indexed

  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const firstWeekday = new Date(viewYear, viewMonth, 1).getDay(); // 0=Sun
  const monthName = new Date(viewYear, viewMonth, 1).toLocaleString('default', { month: 'long' });

  const selected = value ? new Date(value + 'T00:00:00') : null;
  const minD = minDate ? new Date(minDate + 'T00:00:00') : null;

  const handleDayClick = (day: number) => {
    const m = String(viewMonth + 1).padStart(2, '0');
    const d = String(day).padStart(2, '0');
    onChange(`${viewYear}-${m}-${d}`);
    setOpen(false);
  };

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1); }
    else setViewMonth(m => m - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1); }
    else setViewMonth(m => m + 1);
  };

  const displayValue = selected
    ? selected.toLocaleDateString('default', { day: 'numeric', month: 'short', year: 'numeric' })
    : label;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer whitespace-nowrap ${
          value
            ? 'bg-brand/10 border-brand/30 text-brand'
            : 'bg-surface-1 border-border text-muted-foreground hover:text-foreground hover:bg-white/[0.04]'
        }`}
      >
        <CalendarIcon size={12} />
        {displayValue}
      </button>

      {open && (
        <div className="absolute top-full mt-2 left-0 z-50 w-64 bg-surface-1 border border-border rounded-xl shadow-2xl p-3 animate-in fade-in-0 slide-in-from-top-2 duration-150">
          {/* Month nav */}
          <div className="flex items-center justify-between mb-3">
            <button onClick={prevMonth} className="p-1 rounded hover:bg-white/[0.06] text-muted-foreground hover:text-foreground transition-colors text-sm">‹</button>
            <span className="text-sm font-semibold text-foreground">{monthName} {viewYear}</span>
            <button onClick={nextMonth} className="p-1 rounded hover:bg-white/[0.06] text-muted-foreground hover:text-foreground transition-colors text-sm">›</button>
          </div>

          {/* Weekday headers */}
          <div className="grid grid-cols-7 mb-1">
            {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map(d => (
              <div key={d} className="text-center text-[10px] text-muted-foreground font-semibold py-1">{d}</div>
            ))}
          </div>

          {/* Day grid */}
          <div className="grid grid-cols-7 gap-y-1">
            {Array.from({ length: firstWeekday }).map((_, i) => (
              <div key={`empty-${i}`} />
            ))}
            {Array.from({ length: daysInMonth }).map((_, i) => {
              const day = i + 1;
              const dateStr = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
              const isSelected = selected &&
                selected.getFullYear() === viewYear &&
                selected.getMonth() === viewMonth &&
                selected.getDate() === day;
              const isDisabled = minD && new Date(dateStr + 'T00:00:00') < minD;
              const isToday =
                today.getFullYear() === viewYear &&
                today.getMonth() === viewMonth &&
                today.getDate() === day;

              return (
                <button
                  key={day}
                  disabled={!!isDisabled}
                  onClick={() => handleDayClick(day)}
                  className={`w-full aspect-square rounded-lg text-xs font-medium transition-colors cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed ${
                    isSelected
                      ? 'bg-brand text-brand-foreground shadow-sm'
                      : isToday
                      ? 'border border-brand/40 text-brand hover:bg-brand/10'
                      : 'text-foreground hover:bg-white/[0.06]'
                  }`}
                >
                  {day}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Time Picker ─── */
function TimePicker({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
}) {
  const [hour, setHour] = useState('12');
  const [minute, setMinute] = useState('00');
  const [period, setPeriod] = useState<'AM' | 'PM'>('AM');

  const handleChange = (h: string, m: string, p: 'AM' | 'PM') => {
    setHour(h); setMinute(m); setPeriod(p);
    let h24 = parseInt(h, 10);
    if (p === 'AM' && h24 === 12) h24 = 0;
    if (p === 'PM' && h24 !== 12) h24 += 12;
    onChange(`${String(h24).padStart(2, '0')}:${m}`);
  };

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</span>
      <select
        value={hour}
        onChange={e => handleChange(e.target.value, minute, period)}
        className="px-1.5 py-1 bg-surface-2 border border-border rounded text-xs text-foreground focus:outline-none focus:border-brand/50 cursor-pointer"
      >
        {Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, '0')).map(h => (
          <option key={h} value={h}>{h}</option>
        ))}
      </select>
      <span className="text-muted-foreground text-xs">:</span>
      <select
        value={minute}
        onChange={e => handleChange(hour, e.target.value, period)}
        className="px-1.5 py-1 bg-surface-2 border border-border rounded text-xs text-foreground focus:outline-none focus:border-brand/50 cursor-pointer"
      >
        {['00', '15', '30', '45'].map(m => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
      <div className="flex rounded border border-border overflow-hidden">
        {(['AM', 'PM'] as const).map(p => (
          <button
            key={p}
            onClick={() => handleChange(hour, minute, p)}
            className={`px-2 py-1 text-[10px] font-semibold transition-colors cursor-pointer ${
              period === p ? 'bg-brand text-brand-foreground' : 'bg-surface-2 text-muted-foreground hover:text-foreground'
            }`}
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ─── Date Range Filter Panel ─── */
function DateRangeFilter({
  fromDate, toDate, fromTime, toTime, useTime,
  onFromDate, onToDate, onFromTime, onToTime, onToggleTime, onClear,
}: {
  fromDate: string; toDate: string; fromTime: string; toTime: string; useTime: boolean;
  onFromDate: (v: string) => void; onToDate: (v: string) => void;
  onFromTime: (v: string) => void; onToTime: (v: string) => void;
  onToggleTime: () => void; onClear: () => void;
}) {
  const hasFilter = fromDate || toDate;

  return (
    <div className={`rounded-xl border transition-colors p-4 mb-6 ${
      hasFilter ? 'border-brand/30 bg-brand/5' : 'border-border bg-surface-1'
    }`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <CalendarIcon size={14} className={hasFilter ? 'text-brand' : 'text-muted-foreground'} />
          <span className="text-sm font-semibold text-foreground">Date Range Filter</span>
          {hasFilter && (
            <span className="px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-brand text-brand-foreground uppercase tracking-wide">Active</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* Time toggle */}
          <label className="flex items-center gap-1.5 cursor-pointer text-xs text-muted-foreground select-none">
            <div
              onClick={onToggleTime}
              className={`relative w-8 h-4 rounded-full transition-colors cursor-pointer ${useTime ? 'bg-brand' : 'bg-surface-2 border border-border'}`}
            >
              <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${useTime ? 'left-4.5 translate-x-0' : 'left-0.5'}`} />
            </div>
            Time filter
          </label>
          {hasFilter && (
            <button onClick={onClear} className="text-xs text-muted-foreground hover:text-error flex items-center gap-1 transition-colors cursor-pointer">
              <XIcon size={12} />
              Clear
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-muted-foreground font-medium">From</span>
          <CalendarPicker value={fromDate} onChange={onFromDate} label="Start date" />
          {useTime && fromDate && (
            <TimePicker value={fromTime} onChange={onFromTime} label="" />
          )}
        </div>

        {fromDate && (
          <>
            <span className="text-muted-foreground/50 text-sm">→</span>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-muted-foreground font-medium">To</span>
              <CalendarPicker value={toDate} onChange={onToDate} label="End date" minDate={fromDate} />
              {useTime && toDate && (
                <TimePicker value={toTime} onChange={onToTime} label="" />
              )}
            </div>
          </>
        )}
      </div>

      {fromDate && toDate && (
        <p className="mt-2.5 text-[11px] text-muted-foreground">
          Showing reviews from{' '}
          <span className="text-foreground font-medium">
            {new Date(fromDate).toLocaleDateString('default', { day: 'numeric', month: 'short', year: 'numeric' })}
            {useTime && fromTime ? ` ${fromTime}` : ''}
          </span>
          {' '}to{' '}
          <span className="text-foreground font-medium">
            {new Date(toDate).toLocaleDateString('default', { day: 'numeric', month: 'short', year: 'numeric' })}
            {useTime && toTime ? ` ${toTime}` : ''}
          </span>
        </p>
      )}
    </div>
  );
}

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
      const reviewDate = new Date(review.created_at);
      const startStr = useTime && fromTime ? `${fromDate}T${fromTime}:00` : `${fromDate}T00:00:00`;
      if (reviewDate < new Date(startStr)) return false;
    }
    if (toDate) {
      const reviewDate = new Date(review.created_at);
      const endStr = useTime && toTime ? `${toDate}T${toTime}:59` : `${toDate}T23:59:59`;
      if (reviewDate > new Date(endStr)) return false;
    }

    return true;
  });

  const hasDateFilter = fromDate || toDate;

  return (
    <div className="p-6 md:p-8 max-w-5xl mx-auto">
      <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
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
            className="w-full px-3.5 py-2 bg-surface-1 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/50 transition-colors"
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
