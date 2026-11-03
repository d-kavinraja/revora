'use client';

import { Clock, Eye } from 'lucide-react';
import { EmptyState } from '@/components/shared/empty-state';
import type { BotaniQHistoryItem } from '@/lib/api';
import { useToast } from '@/components/ui/toaster';

interface HistoryTableProps {
  history: BotaniQHistoryItem[];
}

export function HistoryTable({ history }: HistoryTableProps) {
  const { toast } = useToast();

  const viewHistory = (h: BotaniQHistoryItem) => {
    toast({
      title: h.image_filename,
      description: `Prediction: ${h.prediction ?? '—'} · Plant: ${h.plant_name ?? '—'} · Type: ${h.plant_type ?? '—'} · Confidence: ${h.confidence != null ? h.confidence.toFixed(1) + '%' : '—'} · Time: ${h.inference_time_ms != null ? h.inference_time_ms + 'ms' : '—'} · Status: ${h.status}`,
      type: h.status === 'completed' ? 'success' : 'error',
    });
  };

  return (
    <section
      aria-label="Test history"
      className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 min-w-0 transition-colors hover:border-emerald-500/40 focus-within:border-emerald-500/50"
    >
      <div className="flex items-center gap-2 mb-3">
        <span className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 flex items-center justify-center shrink-0">
          <Clock size={16} />
        </span>
        <div className="min-w-0">
          <h2 className="font-semibold text-xl tracking-tight leading-tight text-foreground">Test History</h2>
          <p className="text-sm text-foreground/80 leading-relaxed mt-0.5">
            View your recent model test runs.
          </p>
        </div>
        <span className="ml-auto text-xs text-foreground/80">{history.length} recent run{history.length !== 1 ? 's' : ''}</span>
      </div>
      {history.length === 0 ? (
        <EmptyState
          icon={<Clock size={24} />}
          title="No inference runs yet"
          description="Completed runs will appear here with real predictions and metadata."
        />
      ) : (
        <>
          <div className="md:hidden space-y-2 max-h-[360px] overflow-y-auto pr-0.5">
            {history.map((h, i) => (
              <div
                key={h.id}
                className="rounded-lg border border-border bg-surface-2 p-3 min-w-0"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[11px] text-foreground/70 tabular-nums leading-tight">
                      {String(i + 1).padStart(3, '0')}
                    </p>
                    <p className="text-sm font-medium truncate leading-tight text-foreground">
                      {h.image_filename}
                    </p>
                    <p className="text-xs text-foreground/80 mt-0.5">
                      {h.created_at ? new Date(h.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </p>
                  </div>
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      h.status === 'completed'
                        ? 'bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 border border-emerald-500/40'
                        : 'bg-red-500/10 text-red-800 dark:text-red-300 border border-red-500/40'
                    }`}
                  >
                    {h.status}
                  </span>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-foreground/80">
                  {h.prediction ? (
                    <span className="inline-flex px-2 py-0.5 rounded-full bg-surface-3 border border-border text-foreground/90">
                      {h.prediction}
                    </span>
                  ) : (
                    <span>—</span>
                  )}
                  <span className="tabular-nums">Confidence: {h.confidence != null ? h.confidence.toFixed(1) + '%' : '—'}</span>
                  <span className="tabular-nums">
                    {h.inference_time_ms != null ? `${h.inference_time_ms} ms` : 'N/A'}
                  </span>
                </div>

                <div className="mt-2 flex items-center gap-2">
                  <button
                    onClick={() => viewHistory(h)}
                    className="inline-flex items-center gap-1.5 px-3 min-h-[40px] rounded-md text-xs font-medium border border-border text-foreground/90 hover:text-foreground transition-colors"
                    aria-label={`View details for ${h.image_filename}`}
                  >
                    <Eye size={14} /> View
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="hidden md:block overflow-x-auto rounded-lg border border-border max-h-[360px] overflow-y-auto">
            <table className="w-full text-xs min-w-[720px]" aria-label="BotaniQ inference history">
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-border bg-surface-2 text-foreground/90">
                  <th className="text-left px-4 py-2 font-medium">#</th>
                  <th className="text-left px-4 py-2 font-medium">Image</th>
                  <th className="text-left px-4 py-2 font-medium">Date &amp; Time</th>
                  <th className="text-left px-4 py-2 font-medium">Prediction</th>
                  <th className="text-left px-4 py-2 font-medium">Confidence</th>
                  <th className="text-left px-4 py-2 font-medium">Time</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                  <th className="text-left px-4 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row, i) => (
                  <tr key={row.id} className="border-b border-border/60 hover:bg-surface-2/50 transition-colors">
                    <td className="px-4 py-2.5 text-foreground/80 text-xs">{String(i + 1).padStart(3, '0')}</td>
                    <td className="px-4 py-2.5 font-mono text-foreground/90 max-w-[130px] truncate">{row.image_filename}</td>
                    <td className="px-4 py-2.5 text-foreground/80 text-xs whitespace-nowrap">
                      {row.created_at ? new Date(row.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-foreground/90 max-w-[200px] truncate">{row.prediction ?? '—'}</td>
                    <td className="px-4 py-2.5 tabular-nums text-emerald-800 dark:text-emerald-300 font-semibold">
                      {row.confidence != null ? `${row.confidence.toFixed(1)}%` : '—'}
                    </td>
                    <td className="px-4 py-2.5 tabular-nums text-foreground/80 whitespace-nowrap">
                      {row.inference_time_ms != null ? `${row.inference_time_ms}ms` : '—'}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          row.status === 'completed'
                            ? 'bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 border border-emerald-500/40'
                            : 'bg-red-500/10 text-red-800 dark:text-red-300 border border-red-500/40'
                        }`}
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={() => viewHistory(row)}
                        className="min-w-[40px] min-h-[40px] inline-flex items-center justify-center rounded-md text-foreground/80 hover:text-foreground hover:bg-foreground/5 transition-colors"
                        aria-label={`View details for ${row.image_filename}`}
                        title="View details"
                      >
                        <Eye size={14} />
                      </button>
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
