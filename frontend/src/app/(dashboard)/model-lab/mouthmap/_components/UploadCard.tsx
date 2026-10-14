'use client';

import { useRef, useState, type KeyboardEvent } from 'react';
import { CloudUpload, Disc3, Upload, Video, XCircle } from 'lucide-react';
import type { MouthMapConfig } from '@/lib/api';
import type { SelectedVideo, UploadMode } from './types';
import { fmtBytes, fmtDuration } from './types';

interface UploadCardProps {
  config: MouthMapConfig | null;
  mode: UploadMode;
  onModeChange: (m: UploadMode) => void;
  onFile: (f: File | undefined | null) => void;
  selected: SelectedVideo | null;
  onRemove: () => void;
  error: string | null;
  camActive: boolean;
  recording: boolean;
  recSecs: number;
  liveRef: React.RefObject<HTMLVideoElement | null>;
  onEnableCamera: () => void;
  onCancelCamera: () => void;
  onStartRecording: () => void;
  onStopRecording: () => void;
}

export function UploadCard(props: UploadCardProps) {
  const {
    config,
    mode,
    onModeChange,
    onFile,
    selected,
    onRemove,
    error,
    camActive,
    recording,
    recSecs,
    liveRef,
    onEnableCamera,
    onCancelCamera,
    onStartRecording,
    onStopRecording,
  } = props;
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const formats = (config?.allowed_extensions ?? ['.mp4', '.webm', '.mpg'])
    .join(' / ')
    .toUpperCase();
  const maxMb = config?.max_upload_mb ?? 50;
  const ownSelection =
    selected && (selected.kind === 'upload' || selected.kind === 'record')
      ? selected
      : null;
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const onTabKeyDown = (
    e: KeyboardEvent<HTMLButtonElement>,
    index: number,
    tabs: { id: UploadMode; label: string }[],
  ) => {
    let next: number | null = null;
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    e.preventDefault();
    tabRefs.current[next]?.focus();
    onModeChange(tabs[next].id);
  };

  return (
    <section
      aria-label="Upload test video"
      className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 flex flex-col h-full min-w-0 transition-colors hover:border-brand/30"
    >
      <div className="flex items-center gap-2">
        <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
          <Upload size={20} />
        </span>
        <div className="min-w-0">
          <h2 className="font-semibold text-lg sm:text-xl tracking-tight leading-tight">Upload Test Video</h2>
          <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
            Upload a video to test the MouthMap model.
          </p>
        </div>
      </div>

      <div
        className="flex gap-1 mt-3 p-1 rounded-lg bg-surface-2 border border-border"
        role="tablist"
        aria-label="Upload or record"
      >
        {(
          [
            { id: 'upload', label: 'Upload' },
            { id: 'record', label: 'Record' },
          ] as { id: UploadMode; label: string }[]
        ).map((t, i, arr) => (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[i] = el;
            }}
            role="tab"
            id={`ml-upload-tab-${t.id}`}
            aria-selected={mode === t.id}
            aria-controls="ml-upload-panel"
            tabIndex={mode === t.id ? 0 : -1}
            onKeyDown={(e) => onTabKeyDown(e, i, arr)}
            onClick={() => onModeChange(t.id)}
            className={`flex-1 px-3 min-h-[40px] inline-flex items-center justify-center rounded-md text-xs font-medium transition-colors ${
              mode === t.id
                ? 'bg-surface-1 text-foreground shadow-sm border border-border'
                : 'text-foreground/60 hover:text-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div
        className="mt-3 flex flex-col flex-1 min-h-0"
        role="tabpanel"
        id="ml-upload-panel"
        aria-labelledby={mode === 'upload' ? 'ml-upload-tab-upload' : 'ml-upload-tab-record'}
      >
        {mode === 'upload' ? (
          <>
            <div
               onDragOver={(e) => {
                 e.preventDefault();
                 setDragOver(true);
               }}
               onDragLeave={() => setDragOver(false)}
               onDrop={(e) => {
                 e.preventDefault();
                 setDragOver(false);
                 onFile(e.dataTransfer.files?.[0]);
               }}
               onClick={() => fileRef.current?.click()}
               onKeyDown={(e) => {
                 if (e.key === 'Enter' || e.key === ' ') {
                   e.preventDefault();
                   fileRef.current?.click();
                 }
               }}
               role="button"
               tabIndex={0}
               aria-label="Drag and drop a video file here, or click to browse"
                className={`flex-1 flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-3 sm:p-4 text-center transition-all cursor-pointer ${
                 dragOver
                   ? 'border-ai-purple bg-ai-purple/5 scale-[1.01]'
                   : 'border-border bg-surface-2 hover:border-ai-purple/40'
               }`}
             >
              <CloudUpload
                 size={30}
                 className="mx-auto text-ai-purple mb-1.5"
                 aria-hidden="true"
               />
               <p className="text-sm font-semibold tracking-tight">Drag and drop a video file here</p>
               <p className="text-xs text-foreground/65 mt-0.5">or click to browse</p>
              <input
                ref={fileRef}
                type="file"
                accept=".mp4,.webm,.mpg,video/mp4,video/webm,video/mpeg"
                className="hidden"
                aria-label="Choose video file"
                onChange={(e) => onFile(e.target.files?.[0])}
              />
              <button
                onClick={() => fileRef.current?.click()}
                className="mt-2.5 px-4 min-h-[40px] inline-flex items-center justify-center rounded-lg text-sm font-medium bg-brand text-brand-foreground hover:bg-brand-hover transition-colors"
              >
                Choose Video
              </button>
            </div>
            <p className="text-xs text-foreground/65 mt-2 text-center">
              Supported formats: {formats} · Max size: {maxMb} MB
            </p>
          </>
        ) : (
          <div className="flex-1 rounded-lg bg-surface-2 p-3 flex flex-col">
            {!camActive && !ownSelection ? (
              <div className="text-center py-3 flex-1 flex flex-col items-center justify-center">
                <Video size={26} className="mx-auto text-ai-purple mb-1.5" aria-hidden="true" />
                <p className="text-sm text-foreground/70 px-2 leading-relaxed">
                  Allow camera/microphone access to record a lip-reading sample.
                </p>
                <button
                  onClick={onEnableCamera}
                  className="mt-2.5 px-4 min-h-[40px] inline-flex items-center justify-center rounded-lg text-sm font-medium bg-brand text-brand-foreground hover:bg-brand-hover transition-colors"
                >
                  Enable Camera
                </button>
              </div>
            ) : null}
            {camActive && (
              <div className="flex-1 flex flex-col">
                <video
                  ref={liveRef}
                  autoPlay
                  muted
                  playsInline
                  aria-label="Live camera preview"
                  className="w-full rounded-lg bg-black aspect-video object-cover"
                />
                <div className="flex items-center gap-2 mt-2.5 flex-wrap">
                  {recording && (
                    <span
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-error"
                      role="status"
                    >
                      <span className="w-2 h-2 rounded-full bg-error animate-pulse" />
                      <span className="tabular-nums">{recSecs}s</span>
                     </span>
                  )}
                  {!recording ? (
                    <button
                      onClick={onStartRecording}
                      className="px-4 min-h-[40px] inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium bg-error text-white hover:opacity-90 transition-opacity"
                    >
                      <Disc3 size={15} /> Start Recording
                    </button>
                  ) : (
                    <button
                      onClick={onStopRecording}
                      className="px-4 min-h-[40px] inline-flex items-center justify-center rounded-lg text-sm font-medium bg-surface-3 border border-border hover:text-foreground text-muted-foreground transition-colors"
                    >
                      Stop Recording
                    </button>
                  )}
                  <button
                    onClick={onCancelCamera}
                    className="px-3 min-h-[40px] inline-flex items-center rounded-lg text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {ownSelection && (
          <div className="mt-2.5 rounded-lg bg-surface-2 p-2.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium truncate">{ownSelection.filename}</p>
              <button
                onClick={onRemove}
                className="shrink-0 text-muted-foreground hover:text-error transition-colors"
                aria-label="Remove selected video"
              >
                <XCircle size={15} />
              </button>
            </div>
            <p className="text-foreground/70 mt-0.5">
              {fmtDuration(ownSelection.durationS)} ·{' '}
              {ownSelection.resolution ?? 'N/A'} · {fmtBytes(ownSelection.sizeBytes)}
            </p>
            {mode === 'record' && !camActive && (
              <button
                onClick={onEnableCamera}
                className="mt-1.5 text-xs font-medium text-ai-purple hover:underline"
              >
                Re-record
              </button>
            )}
          </div>
        )}
        {error && !selected && (
          <div
            className="mt-2.5 text-xs text-error flex items-start gap-1.5"
            role="alert"
            aria-live="polite"
          >
            <XCircle size={14} className="mt-0.5 shrink-0" /> <span>{error}</span>
          </div>
        )}
      </div>
    </section>
  );
}
