'use client';

import { useEffect, useState, useCallback, use } from 'react';
import { api, Review } from '@/lib/api';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { TriangleAlertIcon, CodeIcon } from '@animateicons/react/lucide';

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; dot: string }> = {
    pending:   { label: 'Pending',   cls: 'bg-yellow-500/10 text-yellow-300 border-yellow-500/30',   dot: 'bg-yellow-400' },
    running:   { label: 'Running',   cls: 'bg-blue-500/10   text-blue-300   border-blue-500/30',     dot: 'bg-blue-400 animate-pulse' },
    completed: { label: 'Completed', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30', dot: 'bg-emerald-400' },
    failed:    { label: 'Failed',    cls: 'bg-red-500/10    text-red-300    border-red-500/30',       dot: 'bg-red-400' },
  };
  const s = map[status] ?? { label: status, cls: 'bg-zinc-800 text-zinc-400 border-zinc-700', dot: 'bg-zinc-500' };
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium border ${s.cls}`}>
      <span className={`w-2 h-2 rounded-full ${s.dot}`} />
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
    // Keep polling if the review is still in progress
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
      <div className="p-8 max-w-5xl mx-auto">
        <div className="h-8 w-64 bg-zinc-900 rounded-lg animate-pulse mb-6" />
        <div className="h-32 bg-zinc-950 border border-white/5 rounded-2xl animate-pulse mb-6" />
        <div className="space-y-4">
          {[...Array(8)].map((_, i) => <div key={i} className="h-4 bg-zinc-900 rounded animate-pulse" />)}
        </div>
      </div>
    );
  }

  if (!review) {
    return (
      <div className="p-8 max-w-5xl mx-auto text-center">
        <p className="text-zinc-400 text-lg">Review not found.</p>
        <Link href="/reviews" className="text-indigo-400 hover:underline mt-2 block">← Back to Reviews</Link>
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
    <div className="p-8 max-w-5xl mx-auto">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-zinc-500 mb-6">
        <Link href="/dashboard" className="hover:text-zinc-300 transition-colors">Dashboard</Link>
        <span>/</span>
        <Link href="/reviews" className="hover:text-zinc-300 transition-colors">Reviews</Link>
        <span>/</span>
        <span className="text-zinc-300 font-mono">#{pr?.pr_number}</span>
      </div>

      {/* PR Header */}
      <div className="rounded-2xl border border-white/5 bg-zinc-950 p-6 mb-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-2 flex-wrap">
              <StatusBadge status={review.status} />
              <span className="text-xs text-zinc-500">{timeAgo(review.created_at)}</span>
            </div>
            <h1 className="text-2xl font-bold text-white leading-snug">{pr?.title}</h1>
            <p className="text-indigo-400/80 text-sm mt-1 font-medium">{repo?.full_name}</p>
          </div>
        </div>

        {/* Meta grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6 pt-5 border-t border-white/5">
          <div>
            <div className="text-xs text-zinc-500 font-medium mb-0.5">PR Number</div>
            <div className="text-sm font-semibold text-white">#{pr?.pr_number}</div>
          </div>
          <div>
            <div className="text-xs text-zinc-500 font-medium mb-0.5">Author</div>
            <div className="text-sm font-semibold text-white">@{pr?.author}</div>
          </div>
          <div>
            <div className="text-xs text-zinc-500 font-medium mb-0.5">Branch</div>
            <div className="text-sm font-semibold text-white truncate font-mono text-xs">
              {pr?.head_branch} → {pr?.base_branch}
            </div>
          </div>
          <div>
            <div className="text-xs text-zinc-500 font-medium mb-0.5">Changes</div>
            <div className="text-sm font-semibold">
              <span className="text-emerald-400">+{pr?.additions}</span>
              {' '}
              <span className="text-red-400">-{pr?.deletions}</span>
              <span className="text-zinc-500 text-xs"> ({pr?.changed_files} files)</span>
            </div>
          </div>
          {duration !== null && (
            <div>
              <div className="text-xs text-zinc-500 font-medium mb-0.5">Review Time</div>
              <div className="text-sm font-semibold text-white">{duration}s</div>
            </div>
          )}
        </div>
      </div>

      {/* Review Status States */}
      {review.status === 'running' && (
        <div className="rounded-2xl border border-blue-500/20 bg-blue-500/5 p-8 mb-6 text-center">
          <div className="w-12 h-12 mx-auto mb-4 relative">
            <div className="w-12 h-12 rounded-full border-2 border-blue-500/20" />
            <div className="absolute inset-0 flex items-center justify-center text-blue-400">
              <LoaderIcon size={24} className="text-blue-400" />
            </div>
          </div>
          <p className="text-blue-300 font-semibold text-lg">AI Review In Progress</p>
          <p className="text-zinc-500 text-sm mt-1">Gemini is analyzing your code... This page will update automatically.</p>
        </div>
      )}

      {review.status === 'pending' && (
        <div className="rounded-2xl border border-yellow-500/20 bg-yellow-500/5 p-8 mb-6 text-center">
          <p className="text-yellow-300 font-semibold text-lg">Review Queued</p>
          <p className="text-zinc-500 text-sm mt-1">Waiting to start processing...</p>
        </div>
      )}

      {review.status === 'failed' && (
        <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-6 mb-6">
          <div className="flex items-start gap-3">
            <TriangleAlertIcon size={20} className="text-red-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-red-300 font-semibold">Review Failed</p>
              {review.error_message && (
                <p className="text-zinc-500 text-sm mt-1 font-mono">{review.error_message}</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* AI Review Markdown Output */}
      {review.status === 'completed' && review.summary && (
        <div className="rounded-2xl border border-white/5 bg-zinc-950 overflow-hidden">
          <div className="flex items-center gap-3 px-6 py-4 border-b border-white/5 bg-black/20">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shrink-0 text-white">
              <CodeIcon size={14} />
            </div>
            <div>
              <span className="text-sm font-semibold text-white">Gemini AI Review</span>
              <span className="text-xs text-zinc-500 ml-2">
                {(review.stats as Record<string, string>)?.provider} · {(review.stats as Record<string, string>)?.model}
              </span>
            </div>
          </div>
          <div className="p-6 md:p-8 prose prose-invert prose-sm max-w-none
            prose-headings:text-white prose-headings:font-bold prose-headings:border-b prose-headings:border-white/10 prose-headings:pb-2
            prose-h1:text-xl prose-h2:text-lg prose-h3:text-base
            prose-p:text-zinc-300 prose-p:leading-relaxed
            prose-strong:text-white
            prose-code:text-indigo-300 prose-code:bg-indigo-500/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-sm prose-code:before:content-none prose-code:after:content-none
            prose-pre:bg-zinc-900 prose-pre:border prose-pre:border-white/5 prose-pre:rounded-xl prose-pre:text-sm
            prose-ul:text-zinc-300 prose-ol:text-zinc-300
            prose-li:marker:text-indigo-400
            prose-blockquote:border-l-indigo-500 prose-blockquote:text-zinc-400
            prose-a:text-indigo-400 prose-a:no-underline hover:prose-a:underline
            prose-table:text-sm prose-th:text-zinc-300 prose-td:text-zinc-400 prose-th:border-white/10 prose-td:border-white/5
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
