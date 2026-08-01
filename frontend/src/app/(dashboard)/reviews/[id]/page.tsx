'use client';

import { use } from 'react';
import { api, Review } from '@/lib/api';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { TriangleAlertIcon, ChevronRightIcon } from '@animateicons/react/lucide';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { StatusBadge } from '@/components/shared/status-badge';
import { formatDateTimeWithRelative } from '@/components/shared/time-ago';
import { SkeletonText } from '@/components/shared/skeleton';
import { ProviderIcon } from '@/components/ui/provider-icon';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { LockIcon, History, BarChart3, Hourglass } from 'lucide-react';
import { motion } from 'framer-motion';
import { useState } from 'react';
import { ReviewActions } from '@/components/shared/review-actions';
import { useReviewStream, reviewStreamUrl } from '@/lib/events';

type TimelineEntry = {
  id: string;
  stage: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  message: string | null;
  metrics: Record<string, unknown>;
};

export default function ReviewDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const queryClient = useQueryClient();
  const { id } = use(params);
  const [showHistory, setShowHistory] = useState(false);
  const [showTimeline, setShowTimeline] = useState(false);
  const [actioningReview, setActioningReview] = useState<string | null>(null);

  const { data: review, isLoading: loading, error, refetch } = useQuery({
    queryKey: ['review', id],
    queryFn: () => api.getReview(id),
    refetchInterval: (query) => {
      const data = query.state.data as Review | undefined;
      const terminal = ['completed', 'failed', 'cancelled', 'stopped', 'timed_out'];
      // Keep polling while a sibling review for this PR is active, so the
      // lifecycle buttons reflect the active-review lock as it changes.
      return (data && terminal.includes(data.status) && !data.pr_has_active_review) ? false : 30000;
    },
    retry: false,
  });

  // Real-time: refresh the moment this review or its PR changes state;
  // the 30s polling interval above is the fallback when SSE drops.
  useReviewStream(reviewStreamUrl(id), (event) => {
    if (event.type === 'review.updated' || event.type === 'pr.state') {
      queryClient.invalidateQueries({ queryKey: ['review', id] });
    }
  });

  // Fetch review history
  const { data: historyData } = useQuery({
    queryKey: ['review-history', id],
    queryFn: () => api.getReviewHistory(id),
    enabled: showHistory,
  });

  // Fetch review timeline
  const { data: timelineData } = useQuery({
    queryKey: ['review-timeline', id],
    queryFn: () => api.getReviewTimeline(id),
    enabled: showTimeline,
  });

  // Lifecycle mutations — the same review row is reused, so refresh it in place
  const rerunMutation = useMutation({
    mutationFn: () => api.rerunReview(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reviews'] });
      refetch();
    },
    onError: (err: any) => {
      console.error('Rerun failed:', err.response?.data?.detail || err.message);
    },
  });

  const retryMutation = useMutation({
    mutationFn: () => api.retryReview(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reviews'] });
      refetch();
    },
    onError: (err: any) => {
      console.error('Retry failed:', err.response?.data?.detail || err.message);
    },
  });

  const restartMutation = useMutation({
    mutationFn: () => api.restartReview(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reviews'] });
      refetch();
    },
    onError: (err: any) => {
      console.error('Restart failed:', err.response?.data?.detail || err.message);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelReview(id),
    onSuccess: () => refetch(),
    onError: (err: any) => {
      console.error('Cancel failed:', err.response?.data?.detail || err.message);
    },
  });

  const handleLifecycleAction = async (action: string) => {
    // Mirror the backend's per-PR active-review lock: a terminal review cannot
    // rerun/retry/restart while another review for the same PR is active.
    if (review?.pr_has_active_review && action !== 'cancel') return;
    setActioningReview(action);
    try {
      switch (action) {
        case 'rerun': await rerunMutation.mutateAsync(); break;
        case 'retry': await retryMutation.mutateAsync(); break;
        case 'restart': await restartMutation.mutateAsync(); break;
        case 'cancel': await cancelMutation.mutateAsync(); break;
      }
    } finally {
      setActioningReview(null);
    }
  };

  if (loading) {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <div className="h-6 w-48 bg-surface-1 rounded-lg animate-pulse mb-6" />
        <div className="h-28 bg-surface-1 border border-border rounded-xl animate-pulse mb-6" />
        <SkeletonText lines={8} />
      </div>
    );
  }

  if (error) {
    const is404 = (error as any).response?.status === 404;
    
    if (is404) {
      return (
        <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 text-center">
          <p className="text-muted-foreground text-lg">Review not found.</p>
          <Link href="/reviews" className="text-brand hover:underline mt-2 block">Back to Reviews</Link>
        </div>
      );
    }
    
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 text-center">
        <div className="p-4 bg-error/10 border border-error/20 rounded-xl max-w-md mx-auto">
          <TriangleAlertIcon size={32} className="text-error mx-auto mb-3" />
          <h2 className="text-lg font-bold text-foreground">Failed to load review</h2>
          <p className="text-muted-foreground text-sm mt-1 mb-4">{(error as any).message || 'An unexpected error occurred.'}</p>
          <button onClick={() => refetch()} className="px-4 py-2 bg-brand hover:bg-brand-hover text-brand-foreground rounded-lg text-sm font-semibold transition-colors">
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!review) return null;

  const pr = review.pull_request;
  const reviewProvider = ((review.stats as Record<string, string>)?.provider || 'gemini').toLowerCase();

  const providerMeta: Record<string, { label: string; gradient: string }> = {
    gemini: { label: 'Gemini AI Review', gradient: 'from-blue-500 to-brand' },
    openai: { label: 'OpenAI Review', gradient: 'from-green-500 to-teal-500' },
    anthropic: { label: 'Claude AI Review', gradient: 'from-orange-500 to-amber-500' },
    grok: { label: 'Grok AI Review', gradient: 'from-gray-600 to-gray-800' },
    groq: { label: 'Groq Review', gradient: 'from-pink-500 to-red-500' },
    deepseek: { label: 'DeepSeek Review', gradient: 'from-sky-500 to-blue-600' },
  };
  const meta = providerMeta[reviewProvider] ?? { label: 'AI Review', gradient: 'from-brand to-brand/80' };
  const repo = review.repository;
  const duration =
    review.started_at && review.completed_at
      ? Math.round((new Date(review.completed_at).getTime() - new Date(review.started_at).getTime()) / 1000)
      : null;

  /* ─── PR State indicator ─── */
  const prState = review.github_pr_state;
  const prStateIndicator = prState && prState !== 'open' && prState !== 'unknown' ? (
    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold bg-error/10 text-error border border-error/20">
      <LockIcon size={10} />
      PR {prState === 'closed' ? 'Closed' : prState === 'merged' ? 'Merged' : prState}
    </span>
  ) : null;

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-muted-foreground mb-8" aria-label="Breadcrumb">
        <Link href="/dashboard" className="hover:text-foreground transition-colors">Dashboard</Link>
        <ChevronRightIcon size={12} className="text-border" />
        <Link href="/reviews" className="hover:text-foreground transition-colors">Reviews</Link>
        <ChevronRightIcon size={12} className="text-border" />
        <span className="text-foreground font-mono">#{pr?.pr_number}</span>
      </nav>

      {/* PR Header */}
      <div className="rounded-xl border border-border bg-surface-1 p-5 mb-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 mb-2 flex-wrap">
              <StatusBadge status={review.status} size="md" />
              <span className="text-xs text-muted-foreground">{formatDateTimeWithRelative(review.created_at)}</span>
            </div>
            <h1 className="text-xl md:text-2xl font-bold text-foreground leading-snug">{pr?.title}</h1>
            <p className="text-brand/80 text-sm mt-1 font-medium">{repo?.full_name}</p>
            <div className="flex items-center gap-2 mt-2">
              {prStateIndicator}
            </div>
          </div>
        </div>

        {/* Meta grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5 pt-4 border-t border-border">
          <div>
            <div className="text-[11px] text-muted-foreground font-medium uppercase tracking-wide mb-0.5">PR Number</div>
            <div className="text-sm font-semibold text-foreground">#{pr?.pr_number}</div>
          </div>
          <div>
            <div className="text-[11px] text-muted-foreground font-medium uppercase tracking-wide mb-0.5">Author</div>
            <div className="text-sm font-semibold text-foreground">@{pr?.author}</div>
          </div>
          <div>
            <div className="text-[11px] text-muted-foreground font-medium uppercase tracking-wide mb-0.5">Branch</div>
            <div className="text-sm font-semibold text-foreground truncate font-mono text-xs">
              {pr?.head_branch} &rarr; {pr?.base_branch}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-muted-foreground font-medium uppercase tracking-wide mb-0.5">Changes</div>
            <div className="text-sm font-semibold">
              <span className="text-success">+{pr?.additions}</span>
              {' '}
              <span className="text-error">-{pr?.deletions}</span>
              <span className="text-muted-foreground text-xs"> ({pr?.changed_files} files)</span>
            </div>
          </div>
          {duration !== null && (
            <div>
              <div className="text-[11px] text-muted-foreground font-medium uppercase tracking-wide mb-0.5">Review Time</div>
              <div className="text-sm font-semibold text-foreground">{duration}s</div>
            </div>
          )}
          {(review.stats as Record<string, any>)?.verified_findings !== undefined && (
            <div>
              <div className="text-[11px] text-brand font-bold uppercase tracking-wide mb-0.5 flex items-center gap-1">
                <TriangleAlertIcon size={10} className="text-brand" /> Machine Verified
              </div>
              <div className="text-sm font-semibold">
                <span className="text-success">{(review.stats as Record<string, any>).verified_findings} verified</span>
                {' '}
                <span className="text-muted-foreground text-xs">/ {((review.stats as Record<string, any>).verified_findings || 0) + ((review.stats as Record<string, any>).rejected_findings || 0)} total</span>
              </div>
            </div>
          )}
        </div>
      </div>

      <ReviewActions review={review} onAction={(_, action) => handleLifecycleAction(action)} isActioning={actioningReview !== null} actioningAction={actioningReview} />

      {/* Review Status States */}
      {review.status === 'running' && (
        <div className="rounded-xl border border-info/20 bg-info/5 p-8 mb-5 text-center relative">
          <button 
            onClick={() => cancelMutation.mutate()} 
            disabled={cancelMutation.isPending}
            className="absolute top-4 right-4 px-3 py-1.5 bg-error/10 hover:bg-error/20 text-error border border-error/20 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50"
          >
            {cancelMutation.isPending ? 'Stopping...' : 'Stop Review'}
          </button>
          <div className="w-12 h-12 mx-auto mb-4 relative">
            <div className="w-12 h-12 rounded-full border-2 border-info/20" />
            <div className="absolute inset-0 flex items-center justify-center text-info">
              <LoaderIcon size={24} className="text-info" animate />
            </div>
          </div>
          <p className="text-info font-semibold text-lg">AI Review In Progress</p>
          <p className="text-muted-foreground text-sm mt-1">AI is analyzing your code... This page will update automatically.</p>
        </div>
      )}

      {review.status === 'pending' && (
        <div className="rounded-xl border border-warning/25 bg-warning/5 p-6 mb-5 text-center relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-[2px] bg-warning/10 overflow-hidden">
            <motion.div
              className="h-full w-1/3 bg-gradient-to-r from-transparent via-amber-400 to-transparent"
              animate={{ x: ['-100%', '400%'] }}
              transition={{ duration: 2.8, repeat: Infinity, ease: 'linear' }}
            />
          </div>
          <button 
            onClick={() => cancelMutation.mutate()} 
            disabled={cancelMutation.isPending}
            className="absolute top-4 right-4 px-3 py-1.5 bg-error/10 hover:bg-error/20 text-error border border-error/20 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50"
          >
            {cancelMutation.isPending ? 'Stopping...' : 'Stop Review'}
          </button>
          <motion.div
            className="w-10 h-10 mx-auto mb-3 flex items-center justify-center text-warning"
            animate={{ opacity: [0.55, 1, 0.55], scale: [0.92, 1, 0.92] }}
            transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
          >
            <Hourglass size={26} strokeWidth={1.75} />
          </motion.div>
          <p className="text-warning font-semibold text-lg">Review Queued</p>
          <p className="text-muted-foreground text-sm mt-1">Waiting for an available worker&hellip;</p>
        </div>
      )}

      {review.status === 'failed' && (
        <div className="rounded-xl border border-error/30 bg-surface-1 overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-3 border-b border-border bg-error/5">
            <div className="w-6 h-6 rounded-md bg-error/15 flex items-center justify-center shrink-0 text-error">
              <TriangleAlertIcon size={12} className="text-error animate-pulse" />
            </div>
            <div>
              <span className="text-sm font-semibold text-error">AI Review Failed</span>
              {review.stats && (review.stats as Record<string, string>).provider && (
                <span className="flex items-center text-xs text-muted-foreground ml-2 gap-1.5">
                  <ProviderIcon slug={(review.stats as Record<string, string>).provider} size={12} />
                  {(review.stats as Record<string, string>).provider} &middot; {(review.stats as Record<string, string>).model}
                </span>
              )}
            </div>
          </div>
          <div className="p-5 md:p-6 space-y-4">
            <div>
              <h3 className="text-sm font-bold text-foreground mb-2">Error Details</h3>
              <div className="p-4 bg-surface-2 border border-border rounded-lg text-xs font-mono text-error/90 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                {review.error_message || 'An unknown error occurred during execution.'}
              </div>
            </div>
            {review.stats && Object.keys(review.stats).length > 0 && (
              <div>
                <h3 className="text-sm font-bold text-foreground mb-2">Execution Metrics</h3>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 bg-surface-2/50 border border-border rounded-lg p-3 text-xs">
                  {Object.entries(review.stats).map(([key, val]) => (
                    <div key={key} className="flex flex-col">
                      <span className="text-muted-foreground uppercase text-[10px] tracking-wide">{key.replace(/_/g, ' ')}</span>
                      <span className="font-semibold text-foreground mt-0.5">{String(val)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* AI Review Markdown Output */}
      {review.status === 'completed' && review.summary ? (
        <div className="rounded-xl border border-border bg-surface-1 overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-3 border-b border-border">
            <div className="shrink-0 flex items-center justify-center">
              <ProviderIcon slug={reviewProvider} size={24} />
            </div>
            <div>
              <span className="text-sm font-semibold text-foreground">{meta.label}</span>
              <span className="flex items-center text-xs text-muted-foreground ml-2 gap-1.5">
                {(review.stats as Record<string, string>)?.provider} &middot; {(review.stats as Record<string, string>)?.model}
              </span>
            </div>
          </div>
          <div className="p-5 md:p-6 prose prose-invert prose-sm max-w-none
            prose-headings:text-foreground prose-headings:font-bold prose-headings:border-b prose-headings:border-border prose-headings:pb-2
            prose-h1:text-xl prose-h2:text-lg prose-h3:text-base
            prose-p:text-muted-foreground prose-p:leading-relaxed
            prose-strong:text-foreground
            prose-code:text-brand prose-code:bg-brand/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-sm prose-code:before:content-none prose-code:after:content-none
            prose-pre:bg-surface-2 prose-pre:border prose-pre:border-border prose-pre:rounded-xl prose-pre:text-sm
            prose-ul:text-muted-foreground prose-ol:text-muted-foreground
            prose-li:marker:text-brand
            prose-blockquote:border-l-brand prose-blockquote:text-muted-foreground
            prose-a:text-brand prose-a:no-underline hover:prose-a:underline
            prose-table:text-sm prose-th:text-foreground prose-td:text-muted-foreground prose-th:border-border prose-td:border-border
          ">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {review.summary}
            </ReactMarkdown>
          </div>
        </div>
      ) : review.status === 'completed' ? (
        <div className="rounded-xl border border-border bg-surface-1 overflow-hidden mb-5">
          <div className="flex items-center gap-2.5 px-5 py-3 border-b border-border">
            <div className="shrink-0 flex items-center justify-center">
              <ProviderIcon slug={reviewProvider} size={24} />
            </div>
            <div>
              <span className="text-sm font-semibold text-foreground">{meta.label}</span>
            </div>
          </div>
          <div className="p-6 text-center">
            <p className="text-sm text-muted-foreground">
              No review content was saved for this execution.
            </p>
            {repo?.full_name && pr?.pr_number && (
              <a
                href={`https://github.com/${repo.full_name}/pull/${pr.pr_number}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block mt-2 text-xs text-brand hover:underline"
              >
                View the review on GitHub (pull request #{pr.pr_number})
              </a>
            )}
          </div>
        </div>
      ) : null}

      {/* Review History Toggle */}
      <div className="mt-6">
        <button
          onClick={() => setShowHistory(!showHistory)}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border bg-surface-1 hover:bg-white/[0.04] text-foreground text-sm font-medium transition-colors cursor-pointer"
        >
          <History size={16} />
          Review History for PR #{pr?.pr_number}
          <span className="text-xs text-muted-foreground ml-2">
            {historyData?.history?.length || 0} reviews
          </span>
        </button>

        {showHistory && historyData && (
          <div className="mt-3 rounded-xl border border-border bg-surface-1 overflow-hidden">
            <div className="px-4 py-2 border-b border-border">
              <span className="text-xs text-muted-foreground">Complete review history for this pull request</span>
            </div>
            <div className="divide-y divide-border">
              {historyData.history.map((h: Review) => (
                <Link
                  key={h.id}
                  href={`/reviews/${h.id}`}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors"
                >
                  <StatusBadge status={h.status} size="sm" />
                  <div className="flex-1 min-w-0">
                    <span className="text-xs font-mono text-muted-foreground">PR #{h.pull_request.pr_number} · {h.pull_request.title}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">{formatDateTimeWithRelative(h.created_at)}</span>
                </Link>
              ))}
            </div>

            {historyData.executions && historyData.executions.length > 0 && (
              <>
                <div className="px-4 py-2 border-b border-border bg-surface-2/50">
                  <span className="text-xs text-muted-foreground">Executions for this review ({historyData.executions.length})</span>
                </div>
                <div className="divide-y divide-border">
                  {historyData.executions.map((e) => (
                    <div key={e.id} className="flex items-center gap-3 px-4 py-2.5">
                      <span className="text-[11px] font-mono text-muted-foreground w-24 shrink-0">#{e.execution_number}</span>
                      <span className="text-xs text-muted-foreground w-24 shrink-0">{e.trigger}</span>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                        e.status === 'completed' ? 'bg-success/10 text-success' :
                        e.status === 'failed' ? 'bg-error/10 text-error' :
                        e.status === 'cancelled' ? 'bg-muted/10 text-muted-foreground' :
                        e.status === 'running' ? 'bg-info/10 text-info' :
                        'bg-warning/10 text-warning'
                      }`}>
                        {e.status}
                      </span>
                      {e.model && <span className="text-xs text-muted-foreground truncate">{e.model}</span>}
                      {e.duration_ms !== null && (
                        <span className="text-xs text-muted-foreground ml-auto">{Math.round(e.duration_ms / 1000)}s</span>
                      )}
                      <span className="text-xs text-muted-foreground w-32 text-right shrink-0">{formatDateTimeWithRelative(e.started_at)}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Review Timeline Toggle */}
      <div className="mt-4">
        <button
          onClick={() => setShowTimeline(!showTimeline)}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border bg-surface-1 hover:bg-white/[0.04] text-foreground text-sm font-medium transition-colors cursor-pointer"
        >
          <BarChart3 size={16} />
          Execution Timeline
        </button>

        {showTimeline && timelineData && (
          <div className="mt-3 rounded-xl border border-border bg-surface-1 overflow-hidden">
            <div className="px-4 py-2 border-b border-border">
              <span className="text-xs text-muted-foreground">Pipeline stages for this review</span>
            </div>
            <div className="p-4 space-y-2">
              {timelineData.timeline.map((entry: TimelineEntry) => (
                <div key={entry.id} className="flex items-center gap-3 text-xs">
                  <div className={`w-2 h-2 rounded-full shrink-0 ${
                    entry.status === 'completed' ? 'bg-success' :
                    entry.status === 'failed' ? 'bg-error' :
                    entry.status === 'running' ? 'bg-info animate-pulse' :
                    entry.status === 'skipped' ? 'bg-muted-foreground' :
                    'bg-muted-foreground/50'
                  }`} />
                  <span className="text-foreground font-medium w-48 truncate">{entry.stage}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                    entry.status === 'completed' ? 'bg-success/10 text-success' :
                    entry.status === 'failed' ? 'bg-error/10 text-error' :
                    entry.status === 'running' ? 'bg-info/10 text-info' :
                    'bg-muted/10 text-muted-foreground'
                  }`}>
                    {entry.status}
                  </span>
                  {entry.duration_ms && (
                    <span className="text-muted-foreground ml-auto">{Math.round(entry.duration_ms / 1000)}s</span>
                  )}
                </div>
              ))}
              {timelineData.timeline.length === 0 && (
                <p className="text-xs text-muted-foreground text-center py-4">No timeline data available yet.</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
