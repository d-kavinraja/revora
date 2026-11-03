'use client';

import { useRef, useState } from 'react';
import { Check, Database, ImageIcon, MoreVertical, Play, Plus, Search } from 'lucide-react';
import type { BotaniQSampleImage } from '@/lib/api';
import { EmptyState } from '@/components/shared/empty-state';
import { fmtBytes } from './types';
import type { Phase } from './types';

interface DatasetCardProps {
  dataset: BotaniQSampleImage[];
  selectedId?: string;
  phase: Phase;
  thumbs: Record<string, string>;
  durations: Record<string, number | null>;
  onSelect: (img: BotaniQSampleImage) => void;
  onRun: (img: BotaniQSampleImage) => void;
  onAddImage: () => void;
  busy: boolean;
  loading?: boolean;
}

function RowThumbnail({ url, filename }: { url?: string; filename: string }) {
  if (url) {
    return (
      <>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt={filename}
          className="w-11 h-11 rounded-lg object-cover bg-surface-3 shrink-0 border border-border"
        />
      </>
    );
  }
  return (
    <span className="w-11 h-11 rounded-lg bg-surface-3 border border-border flex items-center justify-center shrink-0 text-foreground/60">
      <ImageIcon size={18} />
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
  onAddImage,
  busy,
  loading,
}: DatasetCardProps) {
  const [filter, setFilter] = useState('');
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const triggerRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const filtered = dataset.filter((img) =>
    filter === '' ||
    img.filename.toLowerCase().includes(filter.toLowerCase()) ||
    (img.plant_name && img.plant_name.toLowerCase().includes(filter.toLowerCase())),
  );

  return (
    <section
      aria-label="Test dataset"
      className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 flex flex-col h-full min-h-0 min-w-0 relative transition-colors hover:border-emerald-500/40 focus-within:border-emerald-500/50"
    >
      <div className="shrink-0 flex items-center gap-2 flex-wrap pb-3">
        <span className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 flex items-center justify-center shrink-0">
          <Database size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-lg sm:text-xl tracking-tight leading-tight text-foreground">Test Dataset</h2>
          <p className="hidden sm:block text-sm text-foreground/80 leading-relaxed mt-0.5">
            Manage and select test images for inference.
          </p>
        </div>
        <button
          onClick={onAddImage}
          className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-emerald-500/40 text-emerald-800 dark:text-emerald-300 hover:bg-emerald-500/10 transition-colors"
        >
          <Plus size={14} /> Add Image
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8 gap-2 text-foreground/80 text-sm">
          <ImageIcon size={16} className="animate-pulse" /> Loading dataset…
        </div>
      ) : dataset.length === 0 ? (
        <EmptyState
          icon={<Database size={24} />}
          title="No test images yet"
          description="Drop images into backend/app/botaniq/dataset/ to populate the default dataset."
        />
      ) : (
        <>
          <div className="relative mb-2">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-foreground/70" />
            <input
              id="botaniq-dataset-search"
              type="text"
              placeholder="Filter by name…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-border bg-surface-2 text-foreground placeholder:text-foreground/60 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto max-h-[320px] pr-0.5 space-y-2">
            {filtered.map((img) => {
              const active = selectedId === img.id;
              const rowStatus =
                active && (phase === 'uploading' || phase === 'warming' || phase === 'processing')
                  ? 'running'
                  : active && phase === 'failed'
                    ? 'failed'
                    : active && phase === 'completed'
                      ? 'completed'
                      : 'ready';
              return (
                <div
                  key={img.id}
                  onClick={() => {
                    if (!busy) onSelect(img);
                  }}
                  onKeyDown={(e) => {
                    if (!busy && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault();
                      onSelect(img);
                    }
                  }}
                  role="button"
                  tabIndex={busy ? -1 : 0}
                  aria-label={`Select ${img.filename} for inference`}
                  className={`flex items-start gap-2.5 rounded-lg border p-2 transition-colors ${
                    busy ? 'cursor-wait opacity-70' : 'cursor-pointer'
                  } ${
                    active
                      ? 'border-emerald-500/70 bg-emerald-500/10'
                      : 'border-border bg-surface-2 hover:border-emerald-500/40'
                  }`}
                >
                  <RowThumbnail url={thumbs[img.id]} filename={img.filename} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold truncate leading-tight text-foreground">
                      {img.plant_name ?? img.filename}
                    </p>
                    <p className="text-xs text-foreground/80 truncate leading-relaxed">
                      {img.plant_type ?? img.filename}
                      {img.size_bytes ? ` · ${fmtBytes(img.size_bytes)}` : durations[img.id] ? ` · ${Math.round(durations[img.id] || 0)}KB` : ''}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      {rowStatus === 'ready' ? (
                        <span className="inline-flex items-center rounded-full font-medium border px-2 py-0.5 text-xs gap-1.5 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 border-emerald-500/40">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                          Ready
                        </span>
                      ) : rowStatus === 'running' ? (
                        <span className="inline-flex items-center rounded-full font-medium border px-2 py-0.5 text-xs gap-1.5 bg-amber-500/10 text-amber-800 dark:text-amber-300 border-amber-500/40">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                          Running
                        </span>
                      ) : rowStatus === 'completed' ? (
                        <span className="inline-flex items-center rounded-full font-medium border px-2 py-0.5 text-xs gap-1.5 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 border-emerald-500/40">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                          Completed
                        </span>
                      ) : (
                        <span className="inline-flex items-center rounded-full font-medium border px-2 py-0.5 text-xs gap-1.5 bg-red-500/10 text-red-800 dark:text-red-300 border-red-500/40">
                          <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                          Failed
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="relative shrink-0 self-start" onClick={(e) => e.stopPropagation()}>
                    <button
                      ref={(el) => {
                        triggerRefs.current[img.id] = el;
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setOpenMenu(openMenu === img.id ? null : img.id);
                      }}
                      className="min-w-[40px] min-h-[40px] inline-flex items-center justify-center rounded-md text-foreground/70 hover:text-foreground hover:bg-foreground/5 transition-colors"
                      aria-label={`Actions for ${img.filename}`}
                      aria-expanded={openMenu === img.id}
                      disabled={busy}
                    >
                      <MoreVertical size={16} />
                    </button>
                    {openMenu === img.id && (
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
                              triggerRefs.current[img.id]?.focus();
                            }
                          }}
                        >
                          <button
                            onClick={() => {
                              setOpenMenu(null);
                              onSelect(img);
                            }}
                            disabled={busy}
                            className="w-full text-left px-2.5 py-1.5 rounded-md hover:bg-foreground/5 flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed text-foreground"
                          >
                            <Play size={14} className="text-emerald-700 dark:text-emerald-300" /> Select
                          </button>
                          <button
                            onClick={() => {
                              setOpenMenu(null);
                              onRun(img);
                            }}
                            disabled={busy}
                            className="w-full text-left px-2.5 py-1.5 rounded-md hover:bg-foreground/5 flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed text-foreground"
                          >
                            <Check size={14} className="text-emerald-700 dark:text-emerald-300" /> Run Inference
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
            {filtered.length === 0 && (
              <p className="text-xs text-foreground/80 text-center py-4">No matches</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
