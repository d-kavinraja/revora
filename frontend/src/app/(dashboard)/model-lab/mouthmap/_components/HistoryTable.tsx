'use client';

import { Clock, Eye, RotateCcw } from 'lucide-react';
import { StatusBadge } from '@/components/shared/status-badge';
import { EmptyState } from '@/components/shared/empty-state';
import { formatDateTimeWithRelative } from '@/components/shared/time-ago';
import type { MouthMapHistoryItem } from '@/lib/api';
import { metric } from './types';

interface HistoryTableProps {
  history: MouthMapHistoryItem[];
  onRerun: (h: MouthMapHistoryItem) => void;
  onView: (h: MouthMapHistoryItem) => void;
}

export function HistoryTable({ history, onRerun, onView }: HistoryTableProps) {
  return (
    <section
      aria-label="Test history"
      className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 min-w-0 transition-colors hover:border-brand/30"
    >
      <div className="flex items-center gap-2 mb-3">
        <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
          <Clock size={16} />
        </span>
        <div className="min-w-0">
          <h2 className="font-semibold text-xl tracking-tight leading-tight">Test History</h2>
          <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
            View your recent model test runs.
          </p>
        </div>
      </div>
      {history.length === 0 ? (
        <EmptyState
          icon={<Clock size={24} />}
          title="No inference runs yet"
          description="Completed runs will appear here with real predictions and metadata."
        />
      ) : (
        <>
          {/* Mobile: stacked run cards — no horizontal scroll, all cards the
              same width as every other card on the page. */}
          <div className="md:hidden space-y-2">
            {history.map((h, i) => (
              <div
                key={h.id}
                className="rounded-lg border border-border bg-surface-2 p-3 min-w-0"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[11px] text-foreground/50 tabular-nums leading-tight">
                      {String(i + 1).padStart(3, '0')}
                    </p>
                    <p className="text-sm font-medium truncate leading-tight">
                      {h.video_filename}
                    </p>
                    <p className="text-xs text-foreground/60 mt-0.5">
                      {h.created_at ? formatDateTimeWithRelative(h.created_at) : '—'}
                    </p>
                  </div>
                  <StatusBadge status={h.status === 'completed' ? 'completed' : 'failed'} />
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-foreground/65">
                  {h.prediction ? (
                    <span className="inline-flex px-2 py-0.5 rounded-full bg-surface-3 border border-border text-foreground/80">
                      {h.prediction}
                    </span>
                  ) : (
                    <span>—</span>
                  )}
                  <span className="tabular-nums">Confidence: {metric(h.confidence)}</span>
                  <span className="tabular-nums">
                    {h.inference_time_ms != null ? `${h.inference_time_ms} ms` : 'N/A'}
                  </span>
                </div>

                <div className="mt-2 flex items-center gap-2">
                  <button
                    onClick={() => onView(h)}
                    className="inline-flex items-center gap-1.5 px-3 min-h-[40px] rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground transition-colors"
                    aria-label={`View details for ${h.video_filename}`}
                  >
                    <Eye size={14} /> View
                  </button>
                  {h.test_video_id ? (
                    <button
                      onClick={() => onRerun(h)}
                      className="inline-flex items-center gap-1.5 px-3 min-h-[40px] rounded-md text-xs font-medium border border-brand/40 text-brand hover:bg-brand/10 transition-colors"
                      aria-label={`Re-run inference for ${h.video_filename}`}
                    >
                      <RotateCcw size={14} /> Re-run
                    </button>
                  ) : (
                    <span
                      className="inline-flex items-center gap-1.5 px-3 min-h-[40px] rounded-md text-xs text-muted-foreground/40 cursor-not-allowed"
                      title="Only test-dataset videos can be re-run"
                      aria-label="Re-run unavailable for uploads and recordings"
                    >
                      <RotateCcw size={14} /> Re-run
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Desktop: full table. Its own scroll container never affects
              page width. */}
          <div className="hidden md:block overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm min-w-[820px]">
              <thead>
                <tr className="text-left text-xs font-semibold uppercase tracking-wider text-foreground/60 border-b border-border bg-surface-2">
                  <th className="px-3 py-2 font-medium w-10">#</th>
                  <th className="px-3 py-2 font-medium">Video Name</th>
                  <th className="px-3 py-2 font-medium">Date &amp; Time</th>
                  <th className="px-3 py-2 font-medium">Prediction</th>
                  <th className="px-3 py-2 font-medium">Confidence</th>
                  <th className="px-3 py-2 font-medium">Inference Time</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h, i) => (
                  <tr
                    key={h.id}
                    className="border-b border-border last:border-0 hover:bg-foreground/5 transition-colors"
                  >
                    <td className="px-3 py-1.5 text-foreground/60 text-xs">
                      {String(i + 1).padStart(3, '0')}
                    </td>
                    <td className="px-3 py-1.5 font-medium max-w-[220px] truncate">
                      {h.video_filename}
                    </td>
                    <td className="px-3 py-1.5 text-foreground/70 text-xs whitespace-nowrap">
                      {h.created_at ? formatDateTimeWithRelative(h.created_at) : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-foreground/70 max-w-[260px] truncate">
                      {h.prediction ? (
                        <span className="inline-block px-2 py-0.5 rounded-full bg-surface-3 border border-border text-xs">
                          {h.prediction}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-xs">{metric(h.confidence)}</td>
                    <td className="px-3 py-1.5 text-xs whitespace-nowrap">
                      {h.inference_time_ms != null ? `${h.inference_time_ms} ms` : 'N/A'}
                    </td>
                    <td className="px-3 py-1.5">
                      <StatusBadge
                        status={h.status === 'completed' ? 'completed' : 'failed'}
                      />
                    </td>
                    <td className="px-3 py-1.5">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => onView(h)}
                          className="min-w-[40px] min-h-[40px] inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-foreground/10 transition-colors"
                          aria-label={`View details for ${h.video_filename}`}
                          title="View details"
                        >
                          <Eye size={14} />
                        </button>
                        {h.test_video_id ? (
                          <button
                            onClick={() => onRerun(h)}
                            className="min-w-[40px] min-h-[40px] inline-flex items-center justify-center rounded-md text-brand hover:bg-brand/10 transition-colors"
                            aria-label={`Re-run inference for ${h.video_filename}`}
                            title="Re-run inference"
                          >
                            <RotateCcw size={14} />
                          </button>
                        ) : (
                          <span
                            className="p-1.5 text-muted-foreground/40 cursor-not-allowed"
                            title="Only test-dataset videos can be re-run"
                            aria-label="Re-run unavailable for uploads and recordings"
                          >
                            <RotateCcw size={14} />
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
