'use client';

import { Microscope, XCircle } from 'lucide-react';
import { LoaderIcon } from '@/components/ui/loader-icon';
import type { MouthMapInferenceResult } from '@/lib/api';
import type { Phase, SelectedVideo } from './types';
import { OriginalVideoCard } from './OriginalVideoCard';
import { ModelInputRegionCard } from './ModelInputRegionCard';
import { InferenceResultCard } from './InferenceResultCard';
import { InferenceMetricsCard } from './InferenceMetricsCard';
import { InferenceJsonCard } from './InferenceJsonCard';

interface AnalysisSectionProps {
  selected: SelectedVideo | null;
  phase: Phase;
  uploadPct: number;
  result: MouthMapInferenceResult | null;
  error: string | null;
  statusLabel: string | null;
  canRun: boolean;
  running: boolean;
  failed: boolean;
  onRun: () => void;
  onRemove: () => void;
  onMetadata: (durationS: number | null, resolution: string | null) => void;
}

function parseSize(res: string | null | undefined): { w: number; h: number } | null {
  if (!res) return null;
  const m = res.match(/(\d+)\s*x\s*(\d+)/i);
  if (!m) return null;
  return { w: parseInt(m[1], 10), h: parseInt(m[2], 10) };
}

export function AnalysisSection(props: AnalysisSectionProps) {
  const {
    selected,
    phase,
    uploadPct,
    result,
    error,
    statusLabel,
    canRun,
    running,
    failed,
    onRun,
    onRemove,
    onMetadata,
  } = props;

  const jsonData = result
    ? {
        prediction: result.prediction,
        model: result.model,
        model_version: result.model_version,
        confidence: result.confidence,
        inference_time_ms: result.inference_time_ms,
        frames_processed: result.frames_processed,
        status: result.status,
        raw: result.raw,
      }
    : null;

  return (
    <section
      aria-label="Video analysis and results"
      className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 transition-colors hover:border-ai-purple/30"
    >
      {/* Section header — spans the complete width. */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
          <Microscope size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-xl tracking-tight leading-tight">Video Analysis &amp; Results</h2>
          <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
            View inference results and model predictions.
          </p>
        </div>
        <button
          onClick={onRun}
          disabled={!canRun}
          className="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-brand text-brand-foreground hover:bg-brand-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {running ? <LoaderIcon size={15} /> : null}
          {running ? 'Running Inference...' : failed ? 'Retry Inference' : 'Run Inference'}
        </button>
      </div>

      {!selected ? (
        /* Empty state — same two-column shape as Row 1. */
        <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="rounded-xl bg-surface-2 p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
                <Microscope size={20} />
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-xl tracking-tight leading-tight">Original Video</h3>
                <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
                  Test video used for inference
                </p>
              </div>
            </div>
            <div className="rounded-lg bg-black/90 aspect-video flex flex-col items-center justify-center text-white/60 gap-2">
              <Microscope size={26} aria-hidden="true" />
              <p className="text-xs">No video selected</p>
            </div>
          </div>
          <div className="rounded-xl bg-surface-2 p-4 flex flex-col justify-center">
            <p className="text-sm font-semibold tracking-tight">Ready when you are</p>
            <p className="text-sm text-foreground/70 mt-1.5 leading-relaxed">
              Select a test video, upload a file, or record from your camera above.
              The player and prediction workspace will appear here.
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* ROW 1 — Original Video | Model Input Region */}
          <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            <OriginalVideoCard
              key={`original-${selected.testVideoId ?? selected.objectUrl}`}
              selected={selected}
              phase={phase}
              uploadPct={uploadPct}
              statusLabel={statusLabel}
              onRemove={onRemove}
              onMetadata={onMetadata}
            />
            <ModelInputRegionCard
              key={`model-input-${selected.testVideoId ?? selected.objectUrl}`}
              objectUrl={selected.objectUrl}
              frameSize={parseSize(selected.resolution)}
            />
          </div>

          {/* ROW 2 — Inference Result | Inference Metrics | Inference Output (JSON) */}
          <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
            {result && <InferenceResultCard result={result} />}
            {result && <InferenceMetricsCard result={result} />}
            <InferenceJsonCard
              data={jsonData}
              className={result ? 'min-w-0 h-full' : 'min-w-0 lg:col-span-3'}
            />
          </div>
        </>
      )}

      {failed && error && selected && (
        <div
          className="mt-4 rounded-lg border border-error/30 bg-error/5 p-3 flex flex-col sm:flex-row sm:items-center gap-2.5"
          role="alert"
        >
          <span className="w-8 h-8 rounded-lg bg-error/10 text-error flex items-center justify-center shrink-0">
            <XCircle size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold tracking-tight">Inference Failed</p>
            <p className="text-sm text-foreground/70 mt-0.5 break-words leading-relaxed">{error}</p>
          </div>
          <button
            onClick={onRun}
            disabled={!canRun}
            className="shrink-0 px-4 py-2 rounded-lg text-sm font-medium bg-brand text-brand-foreground hover:bg-brand-hover disabled:opacity-50 transition-colors"
          >
            Retry
          </button>
        </div>
      )}
    </section>
  );
}
