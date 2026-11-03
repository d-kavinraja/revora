'use client';

import { useState } from 'react';
import { ImageIcon, Leaf, Loader2, X, XCircle } from 'lucide-react';
import type { Phase, SelectedImage } from './types';

interface ResultsPanelProps {
  selected: SelectedImage | null;
  phase: Phase;
  uploadPct: number;
  error: string | null;
  busy: boolean;
  canRun: boolean;
  failed: boolean;
  onRun: () => void;
  onClear: () => void;
}

export function ResultsPanel(props: ResultsPanelProps) {
  const {
    selected,
    phase,
    uploadPct,
    error,
    busy,
    canRun,
    failed,
    onRun,
    onClear,
  } = props;

  const greenText = 'text-emerald-800 dark:text-emerald-300';
  const [imgError, setImgError] = useState(false);
  const [prevUrl, setPrevUrl] = useState(selected?.objectUrl);
  if (prevUrl !== selected?.objectUrl) {
    setPrevUrl(selected?.objectUrl);
    setImgError(false);
  }

  return (
    <section
      aria-label="Prediction results"
      className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 min-w-0 transition-colors hover:border-emerald-500/40 focus-within:border-emerald-500/50 h-full min-h-[520px] flex flex-col"
    >
      <div className="flex items-center gap-2 flex-wrap mb-4">
        <span className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 flex items-center justify-center shrink-0">
          <ImageIcon size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-xl tracking-tight leading-tight text-foreground">Prediction Results</h2>
          <p className="text-sm text-foreground/80 leading-relaxed mt-0.5">
            View inference results and model predictions.
          </p>
        </div>
      </div>

      {!selected ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
          <Leaf size={48} className="text-foreground/20 mb-4" aria-hidden="true" />
          <p className="text-base font-medium text-foreground/80 mb-1">Select an image to get started</p>
          <p className="text-sm text-foreground/60 leading-relaxed max-w-[300px]">
            Upload, paste a URL, or pick from the test dataset on the left.
          </p>
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-border bg-surface-2 overflow-hidden flex-1 flex flex-col">
            <div className="px-4 py-3 border-b border-border flex items-center justify-between">
              <span className="text-sm font-medium flex items-center gap-1.5 text-foreground">
                <ImageIcon size={14} className={greenText} />
                {selected.kind === 'url' ? 'URL Image' : selected.kind === 'dataset' ? 'Test Image' : 'Uploaded Image'}
              </span>
              <span className="text-xs text-foreground/70 truncate max-w-[50%]">{selected.filename}</span>
            </div>
            <div className="relative bg-surface-3 aspect-video w-full min-h-[320px] flex items-center justify-center overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={selected.objectUrl}
                alt={selected.filename}
                className="max-w-full max-h-full object-contain"
                onError={() => setImgError(true)}
                style={{ display: imgError ? 'none' : undefined }}
              />
              {imgError && (
                <div className="flex flex-col items-center gap-2 text-foreground/70 p-4 text-center">
                  <XCircle size={32} />
                  <p className="text-sm font-medium text-foreground">Preview unavailable</p>
                  <p className="text-xs text-foreground/60 leading-relaxed max-w-[280px]">
                    {selected.kind === 'url'
                      ? 'The URL may not point to a valid image or may be blocked. Inference will validate it.'
                      : 'Could not load the image preview.'}
                  </p>
                </div>
              )}
              {busy && (
                <div className="absolute inset-0 bg-black/60 backdrop-blur-sm flex flex-col items-center justify-center gap-2">
                  <Loader2 size={28} className={`animate-spin ${greenText}`} />
                  <p className="text-sm font-medium text-white">
                    {phase === 'warming' ? 'Waking model…' : phase === 'uploading' ? `Uploading ${uploadPct}%` : 'Running inference…'}
                  </p>
                </div>
              )}
              {!busy && (
                <button
                  onClick={onClear}
                  className="absolute top-2 right-2 p-1.5 rounded-md bg-black/60 text-white/80 hover:text-white transition-colors"
                  aria-label="Clear selected image"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          </div>

          {failed && error && (
            <div
              className="mt-4 rounded-lg border border-red-500/40 bg-red-500/10 p-3 flex flex-col sm:flex-row sm:items-center gap-2.5"
              role="alert"
            >
              <span className="w-8 h-8 rounded-lg bg-red-500/10 text-red-800 dark:text-red-300 flex items-center justify-center shrink-0">
                <XCircle size={16} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold tracking-tight text-foreground">Inference Failed</p>
                <p className="text-sm text-foreground/80 mt-0.5 break-words leading-relaxed">{error}</p>
              </div>
              <button
                onClick={onRun}
                disabled={!canRun}
                className="shrink-0 px-4 py-2 rounded-lg text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50 transition-colors"
              >
                Retry
              </button>
            </div>
          )}

        </>
      )}
    </section>
  );
}