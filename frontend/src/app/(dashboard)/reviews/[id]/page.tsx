'use client';

import { useEffect, useState, useCallback, use } from 'react';
import { api, Review } from '@/lib/api';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { TriangleAlertIcon, ChevronRightIcon } from '@animateicons/react/lucide';
import { StatusBadge } from '@/components/shared/status-badge';
import { timeAgo, formatDateTimeWithRelative } from '@/components/shared/time-ago';
import { SkeletonText } from '@/components/shared/skeleton';
import { Gemini } from '@lobehub/icons';

export default function ReviewDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [review, setReview] = useState<Review | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchReview = useCallback(async () => {
    try {
      const data = await api.getReview(id);
      setReview(data);
    } catch (err) {
      console.error('Failed to load review', err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchReview();
    const interval = setInterval(async () => {
      const data = await api.getReview(id).catch(() => null);
      if (data) {
        setReview(data);
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(interval);
        }
      }
    }, 5_000);
    return () => clearInterval(interval);
  }, [id, fetchReview]);

  if (loading) {
    return (
      <div className="p-6 md:p-8 max-w-5xl mx-auto">
        <div className="h-6 w-48 bg-surface-1 rounded-lg animate-pulse mb-6" />
        <div className="h-28 bg-surface-1 border border-border rounded-xl animate-pulse mb-6" />
        <SkeletonText lines={8} />
      </div>
    );
  }

  if (!review) {
    return (
      <div className="p-6 md:p-8 max-w-5xl mx-auto text-center">
        <p className="text-muted-foreground text-lg">Review not found.</p>
        <Link href="/reviews" className="text-brand hover:underline mt-2 block">Back to Reviews</Link>
      </div>
    );
  }

  const pr = review.pull_request;
  const repo = review.repository;
  const duration =
    review.started_at && review.completed_at
      ? Math.round((new Date(review.completed_at).getTime() - new Date(review.started_at).getTime()) / 1000)
      : null;

  return (
    <div className="p-6 md:p-8 max-w-5xl mx-auto">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-muted-foreground mb-6" aria-label="Breadcrumb">
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
              {pr?.head_branch} → {pr?.base_branch}
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
        </div>
      </div>

      {/* Review Status States */}
      {review.status === 'running' && (
        <div className="rounded-xl border border-info/20 bg-info/5 p-8 mb-5 text-center">
          <div className="w-12 h-12 mx-auto mb-4 relative">
            <div className="w-12 h-12 rounded-full border-2 border-info/20" />
            <div className="absolute inset-0 flex items-center justify-center text-info">
              <LoaderIcon size={24} className="text-info" />
            </div>
          </div>
          <p className="text-info font-semibold text-lg">AI Review In Progress</p>
          <p className="text-muted-foreground text-sm mt-1">Gemini is analyzing your code... This page will update automatically.</p>
        </div>
      )}

      {review.status === 'pending' && (
        <div className="rounded-xl border border-warning/20 bg-warning/5 p-6 mb-5 text-center">
          <p className="text-warning font-semibold text-lg">Review Queued</p>
          <p className="text-muted-foreground text-sm mt-1">Waiting to start processing...</p>
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
                <span className="text-xs text-muted-foreground ml-2">
                  {(review.stats as Record<string, string>).provider} · {(review.stats as Record<string, string>).model}
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
      {review.status === 'completed' && review.summary && (
        <div className="rounded-xl border border-border bg-surface-1 overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-3 border-b border-border">
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-blue-500 to-brand flex items-center justify-center shrink-0 text-white p-1">
              <Gemini size={14} />
            </div>
            <div>
              <span className="text-sm font-semibold text-foreground">Gemini AI Review</span>
              <span className="text-xs text-muted-foreground ml-2">
                {(review.stats as Record<string, string>)?.provider} · {(review.stats as Record<string, string>)?.model}
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
      )}
    </div>
  );
}
