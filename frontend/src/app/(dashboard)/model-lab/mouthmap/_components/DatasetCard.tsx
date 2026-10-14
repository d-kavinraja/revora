'use client';

import { useRef, useState } from 'react';
import { Check, Database, Film, MoreVertical, Play, Plus } from 'lucide-react';
import type { MouthMapTestVideo } from '@/lib/api';
import { StatusBadge } from '@/components/shared/status-badge';
import { EmptyState } from '@/components/shared/empty-state';
import { fmtBytes, fmtClock } from './types';
import type { Phase } from './types';

interface DatasetCardProps {
  dataset: MouthMapTestVideo[];
  selectedId?: string;
  phase: Phase;
  /** Real thumbnail blob URLs per video id (fetched with auth, same bytes). */
  thumbs: Record<string, string>;
  /** Real durations (seconds) per video id, when metadata loaded. */
  durations: Record<string, number | null>;
  onSelect: (v: MouthMapTestVideo) => void;
  onRun: (v: MouthMapTestVideo) => void;
  onAddVideo: () => void;
  busy: boolean;
}

function RowThumbnail({ url, filename }: { url?: string; filename: string }) {
  if (url) {
    return (
      <video
        src={url}
        preload="metadata"
        muted
        playsInline
        aria-label={`Thumbnail for ${filename}`}
        className="w-11 h-11 rounded-lg object-cover bg-black shrink-0 border border-border"
      />
    );
  }
  return (
    <span className="w-11 h-11 rounded-lg bg-surface-3 border border-border flex items-center justify-center shrink-0 text-muted-foreground">
      <Film size={18} />
    </span>
  );
}

export function DatasetCard({
  dataset,
  selectedId,
  phase,
  thumbs,
  durations,
  onSelect,
  onRun,
  onAddVideo,
  busy,
}: DatasetCardProps) {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const triggerRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  return (
    <section
      aria-label="Test dataset"
      className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 flex flex-col h-full min-h-0 relative transition-colors hover:border-ai-purple/30"
    >
      <div className="shrink-0 flex items-center gap-2 pb-3">
        <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
          <Database size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-xl tracking-tight leading-tight">Test Dataset</h2>
          <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
            Manage and select test videos for inference.
          </p>
        </div>
        <button
          onClick={onAddVideo}
          className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-ai-purple/40 text-ai-purple hover:bg-ai-purple/10 transition-colors"
        >
          <Plus size={14} /> Add Video
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden max-h-[264px] pr-0.5 space-y-2">
        {dataset.length === 0 ? (
          <EmptyState
            icon={<Database size={24} />}
            title="No test videos yet"
            description="Provide real MouthMap test videos and .align files to enable the default dataset."
          />
        ) : (
          dataset.map((v) => {
            const active = selectedId === v.id;
            // Row status is derived from the live request phase — it can
            // never get stuck on "Running" after a failure.
            const rowStatus =
              active && (phase === 'uploading' || phase === 'preparing' || phase === 'processing')
                ? 'running'
                : active && phase === 'failed'
                  ? 'failed'
                  : active && phase === 'completed'
                    ? 'completed'
                    : 'ready';
            return (
              <div
                key={v.id}
                onClick={() => {
                  if (!busy) onSelect(v);
                }}
                onKeyDown={(e) => {
                  if (!busy && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault();
                    onSelect(v);
                  }
                }}
                role="button"
                tabIndex={busy ? -1 : 0}
                aria-label={`Select ${v.filename} for inference`}
                className={`flex items-center gap-2.5 rounded-lg border p-2 transition-colors ${
                  busy ? 'cursor-wait opacity-70' : 'cursor-pointer'
                } ${
                  active
                    ? 'border-brand bg-brand/5'
                    : 'border-border bg-surface-2 hover:border-brand/30'
                }`}
              >
                <RowThumbnail url={thumbs[v.id]} filename={v.filename} />
                <div className="min-w-0 flex-1">
                 <p className="text-sm font-semibold truncate leading-tight">
                     {v.filename}
                   </p>
                   <p className="text-xs text-foreground/65 truncate leading-relaxed">
                     {v.resolution ?? fmtBytes(v.size_bytes)}
                     {v.ground_truth ? ` · “${v.ground_truth}”` : ''}
                   </p>
                </div>
                <span className="shrink-0 px-2 py-0.5 rounded-full bg-surface-3 border border-border text-xs text-foreground/75 tabular-nums">
                  {fmtClock(durations[v.id])}
                </span>
                {rowStatus === 'ready' ? (
                  <span className="inline-flex items-center rounded-full font-medium border px-2.5 py-0.5 text-xs gap-1.5 bg-success/10 text-success border-success/30">
                    <span className="w-1.5 h-1.5 rounded-full bg-success" />
                    Ready
                  </span>
                ) : (
                  <StatusBadge status={rowStatus} />
                )}
                <div className="relative shrink-0" onClick={(e) => e.stopPropagation()}>
                  <button
                    ref={(el) => {
                      triggerRefs.current[v.id] = el;
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenMenu(openMenu === v.id ? null : v.id);
                    }}
                    className="min-w-[40px] min-h-[40px] inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-foreground/5 transition-colors"
                    aria-label={`Actions for ${v.filename}`}
                    aria-expanded={openMenu === v.id}
                    disabled={busy}
                  >
                    <MoreVertical size={16} />
                  </button>
                  {openMenu === v.id && (
                    <>
                      <div
                        className="fixed inset-0 z-10"
                        onClick={() => setOpenMenu(null)}
                        aria-hidden="true"
                      />
                      <div
                        className="absolute right-0 top-8 z-20 w-48 rounded-lg border border-border bg-surface-1 shadow-lg p-1 text-sm"
                        role="menu"
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') {
                            e.stopPropagation();
                            setOpenMenu(null);
                            triggerRefs.current[v.id]?.focus();
                          }
                        }}
                      >
                        <button
                          onClick={() => {
                            setOpenMenu(null);
                            onSelect(v);
                          }}
                          disabled={busy}
                          className="w-full text-left px-2.5 py-1.5 rounded-md hover:bg-foreground/5 flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <Play size={14} className="text-brand" /> Select
                        </button>
                        <button
                          onClick={() => {
                            setOpenMenu(null);
                            onRun(v);
                          }}
                          disabled={busy}
                          className="w-full text-left px-2.5 py-1.5 rounded-md hover:bg-foreground/5 flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <Check size={14} className="text-success" /> Run Inference
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
