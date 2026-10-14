'use client';

import { useRef, useState } from 'react';
import { Camera, CheckCircle2, Clapperboard, Database, Proportions, Upload, Video, XCircle } from 'lucide-react';
import { LoaderIcon } from '@/components/ui/loader-icon';
import type { Phase, SelectedVideo } from './types';
import { fmtBytes, fmtDuration } from './types';

function fileFormat(filename: string): string {
  const m = filename.match(/\.([a-z0-9]{2,5})$/i);
  return m ? m[1].toUpperCase() : 'N/A';
}

function aspectRatio(resolution: string | null | undefined): string {
  const m = resolution?.match(/(\d+)\s*x\s*(\d+)/i);
  if (!m) return 'N/A';
  const w = parseInt(m[1], 10);
  const h = parseInt(m[2], 10);
  if (!w || !h) return 'N/A';
  const gcd = (a: number, b: number): number => (b ? gcd(b, a % b) : a);
  const g = gcd(w, h);
  return `${w / g}:${h / g}`;
}

const SOURCE_META = {
  dataset: { icon: Database, label: 'Dataset' },
  upload: { icon: Upload, label: 'Upload' },
  record: { icon: Camera, label: 'Recording' },
} as const;

interface OriginalVideoCardProps {
  selected: SelectedVideo;
  phase: Phase;
  uploadPct: number;
  statusLabel: string | null;
  onRemove: () => void;
  onMetadata: (durationS: number | null, resolution: string | null) => void;
}

export function OriginalVideoCard({
  selected,
  phase,
  uploadPct,
  statusLabel,
  onRemove,
  onMetadata,
}: OriginalVideoCardProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  // Per-video load state. Render-phase reset on identity change so the
  // loader shows immediately for the new video (never the old frame).
  const [loadedUrl, setLoadedUrl] = useState(selected.objectUrl);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading');
  if (loadedUrl !== selected.objectUrl) {
    setLoadedUrl(selected.objectUrl);
    setLoadState('loading');
  }
  const retryLoad = () => {
    setLoadState('loading');
    try {
      videoRef.current?.load();
    } catch {
      setLoadState('error');
    }
  };
  return (
    <div className="rounded-xl border border-border bg-surface-1 p-4 transition-colors hover:border-ai-purple/30 flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
          <Video size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-xl leading-tight">Original Video</h3>
          <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
            Test video used for inference
          </p>
        </div>
        <button
          onClick={onRemove}
          className="shrink-0 px-3 min-h-[40px] inline-flex items-center rounded-lg text-xs border border-border text-muted-foreground hover:text-foreground transition-colors"
        >
          Remove
        </button>
      </div>

      <div className="relative">
        <video
          key={selected.objectUrl}
          ref={videoRef}
          src={selected.objectUrl}
          controls
          playsInline
          preload="metadata"
          className="w-full rounded-lg bg-black aspect-video"
          onLoadStart={() => setLoadState('loading')}
          onLoadedMetadata={(e) => {
            const el = e.currentTarget;
            onMetadata(
              el.duration || null,
              el.videoWidth && el.videoHeight
                ? `${el.videoWidth}x${el.videoHeight}`
                : null,
            );
          }}
          onCanPlay={() => setLoadState('ready')}
          onError={() => setLoadState('error')}
        />
        {loadState !== 'ready' && (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-lg bg-black/70 px-4 text-center"
            role={loadState === 'error' ? 'alert' : 'status'}
          >
            {loadState === 'loading' ? (
              <>
                <LoaderIcon size={20} animate className="text-white" />
                <p className="text-xs font-medium text-white">Loading original frame…</p>
              </>
            ) : (
              <>
                <p className="text-xs font-medium text-white">Could not load this video.</p>
                <button
                  type="button"
                  onClick={retryLoad}
                  className="rounded-md border border-white/30 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-white/10"
                >
                  Retry
                </button>
              </>
            )}
          </div>
        )}
      </div>

      <div className="mt-3 text-sm min-w-0">
        <p className="truncate">
          <span className="text-foreground/60">File: </span>
          <span className="font-medium">{selected.filename}</span>
        </p>
        <p className="text-xs text-foreground/65 mt-0.5">
          {fmtDuration(selected.durationS)} · {selected.resolution ?? 'N/A'} ·{' '}
          {fmtBytes(selected.sizeBytes)}
          {phase === 'uploading' ? ` · Uploading ${uploadPct}%` : ''}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-3">
        {(
          [
            { icon: Clapperboard, label: 'Format', value: fileFormat(selected.filename) },
            { icon: SOURCE_META[selected.kind].icon, label: 'Source', value: SOURCE_META[selected.kind].label },
            { icon: Proportions, label: 'Aspect', value: aspectRatio(selected.resolution) },
          ] as const
        ).map((d) => (
          <div key={d.label} className="rounded-lg bg-surface-2 p-2.5 min-w-0">
            <p className="flex items-center gap-1.5 text-xs text-foreground/65 leading-tight">
              <d.icon size={13} className="text-ai-purple shrink-0" aria-hidden="true" />
              <span className="truncate">{d.label}</span>
            </p>
            <p className="font-semibold text-sm mt-1 truncate" title={d.value}>
              {d.value}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-auto pt-2.5">
        {statusLabel ? (
          <div
             className="text-xs text-ai-purple flex items-center gap-1.5"
            role="status"
          >
            {phase === 'completed' ? (
              <CheckCircle2 size={13} className="text-success shrink-0" />
            ) : (
              <LoaderIcon size={13} />
            )}
            <span>{statusLabel}</span>
          </div>
        ) : phase === 'failed' ? (
          <div className="text-xs text-error flex items-center gap-1.5" role="status">
            <XCircle size={13} className="shrink-0" />
            Inference failed
          </div>
        ) : (
          <div className="text-xs text-foreground/65 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-success shrink-0" aria-hidden="true" />
            Ready for inference
          </div>
        )}
      </div>
    </div>
  );
}
