'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Crop, ScanEye } from 'lucide-react';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { MODEL_INPUT, isSafeMediaUrl } from './types';

export type VizMode = 'crop' | 'full';

interface MouthRegionVizProps {
  /** Object URL of the actual selected video (same bytes sent to inference). */
  objectUrl: string;
  /** Natural frame size, when known (for bounds checking + rect scaling). */
  frameSize: { w: number; h: number } | null;
  /** Which panels to show: both (frame + crop) or only the original frame. */
  mode: VizMode;
}

/**
 * REAL model-input visualization (Option B): the fixed preprocessing crop
 * (x=80 y=190 140x46) drawn over the actual video frame, plus the same
 * crop rendered in grayscale beside it. Explicitly labeled as a fixed
 * preprocessing crop — never presented as detected landmarks.
 * Card chrome, title, and tabs live in ModelInputRegionCard.
 */
export function MouthRegionViz({ objectUrl, frameSize, mode }: MouthRegionVizProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameRef = useRef<HTMLCanvasElement>(null);
  const cropRef = useRef<HTMLCanvasElement>(null);
  // Per-video paint state. Render-phase reset when the video identity
  // changes (the approved alternative to setState inside an effect).
  // Trust boundary (CodeQL js/xss-through-dom): only allowlisted media
  // URLs reach the hidden <video> src below. Anything else keeps status
  // at 'error', so the existing error UI renders instead (fail-closed).
  const safeSrc = isSafeMediaUrl(objectUrl) ? objectUrl : null;
  const [paintUrl, setPaintUrl] = useState(safeSrc);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>(
    safeSrc ? 'loading' : 'error',
  );
  if (paintUrl !== safeSrc) {
    setPaintUrl(safeSrc);
    setStatus(safeSrc ? 'loading' : 'error');
  }

  const clearCanvases = useCallback(() => {
    // Resetting width collapses the bitmap without changing layout size
    // (CSS controls display size), so stale pixels can never survive.
    for (const ref of [frameRef, cropRef]) {
      const canvas = ref.current;
      if (canvas) canvas.width = canvas.width;
    }
  }, []);

  const draw = useCallback(() => {
    const video = videoRef.current;
    const frame = frameRef.current;
    const crop = cropRef.current;
    if (!video || !frame || !crop) return false;
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh || video.readyState < 2) return false;

    // Left: full frame + true crop rect overlay.
    const maxW = 480;
    const scale = Math.min(1, maxW / vw);
    const dw = Math.round(vw * scale);
    const dh = Math.round(vh * scale);
    frame.width = dw;
    frame.height = dh;
    const ctx = frame.getContext('2d');
    if (!ctx) return false;
    ctx.drawImage(video, 0, 0, dw, dh);
    const rx = MODEL_INPUT.x * scale;
    const ry = MODEL_INPUT.y * scale;
    const rw = MODEL_INPUT.w * scale;
    const rh = MODEL_INPUT.h * scale;
    ctx.save();
    ctx.strokeStyle = '#6366f1';
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 3]);
    ctx.strokeRect(rx, ry, rw, rh);
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(99,102,241,0.12)';
    ctx.fillRect(rx, ry, rw, rh);
    // Corner ticks.
    const t = 6;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(rx, ry + t); ctx.lineTo(rx, ry); ctx.lineTo(rx + t, ry);
    ctx.moveTo(rx + rw - t, ry); ctx.lineTo(rx + rw, ry); ctx.lineTo(rx + rw, ry + t);
    ctx.moveTo(rx + rw, ry + rh - t); ctx.lineTo(rx + rw, ry + rh); ctx.lineTo(rx + rw - t, ry + rh);
    ctx.moveTo(rx + t, ry + rh); ctx.lineTo(rx, ry + rh); ctx.lineTo(rx, ry + rh - t);
    ctx.stroke();
    ctx.restore();

    // Right: the same crop in grayscale (same algorithm family as the
    // server pipeline: slice region, luminance grayscale).
    const off = document.createElement('canvas');
    off.width = vw;
    off.height = vh;
    const octx = off.getContext('2d', { willReadFrequently: true });
    if (!octx) return false;
    octx.drawImage(video, 0, 0);
    const cx = Math.max(0, Math.min(MODEL_INPUT.x, vw - 1));
    const cy = Math.max(0, Math.min(MODEL_INPUT.y, vh - 1));
    const cw = Math.max(1, Math.min(MODEL_INPUT.w, vw - cx));
    const ch = Math.max(1, Math.min(MODEL_INPUT.h, vh - cy));
    let img: ImageData;
    try {
      img = octx.getImageData(cx, cy, cw, ch);
    } catch {
      // Canvas taint or decode failure: report, never silently keep stale pixels.
      return false;
    }
    const d = img.data;
    for (let i = 0; i < d.length; i += 4) {
      const g = 0.114 * d[i] + 0.587 * d[i + 1] + 0.299 * d[i + 2];
      d[i] = g;
      d[i + 1] = g;
      d[i + 2] = g;
    }
    crop.width = MODEL_INPUT.w;
    crop.height = MODEL_INPUT.h;
    const cctx = crop.getContext('2d');
    if (!cctx) return false;
    const out = cctx.createImageData(MODEL_INPUT.w, MODEL_INPUT.h);
    out.data.set(d.slice(0, MODEL_INPUT.w * MODEL_INPUT.h * 4));
    // If the frame is smaller than the crop, pad the remainder dark.
    cctx.fillStyle = '#000';
    cctx.fillRect(0, 0, MODEL_INPUT.w, MODEL_INPUT.h);
    cctx.putImageData(out, 0, 0);
    return true;
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    // New video: immediately drop stale pixels underneath the loader
    // overlay (status was already reset to loading during render).
    clearCanvases();
    let raf = 0;
    let last = 0;
    let settled = false;
    const settleReady = () => {
      if (!settled) {
        settled = true;
        setStatus('ready');
      }
    };
    const paint = () => {
      if (draw()) settleReady();
    };
    const stopLoop = () => {
      if (raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    };
    const onFrame = () => {
      raf = 0;
      // Idle unless the frame can actually advance: a paused or
      // hidden video never changes, and seeks repaint via 'seeked'.
      if (video.paused || document.hidden) return;
      const now = performance.now();
      if (now - last > 250) {
        last = now;
        paint();
      }
      raf = requestAnimationFrame(onFrame);
    };
    const kick = () => {
      paint();
      if (!raf && !video.paused && !document.hidden) {
        raf = requestAnimationFrame(onFrame);
      }
    };
    const onSeek = () => paint();
    const onData = () => {
      // Frame bytes available: paint now; nudge a seek so 'seeked'
      // fires even when currentTime is already 0.
      paint();
      try {
        video.currentTime = 0;
      } catch {
        // Seeking unsupported — the direct paint above already ran.
      }
    };
    const onVideoError = () => setStatus('error');
    const onVisibility = () => {
      if (!document.hidden) kick();
    };
    video.addEventListener('seeked', onSeek);
    video.addEventListener('loadeddata', onData);
    video.addEventListener('canplay', paint);
    video.addEventListener('error', onVideoError);
    video.addEventListener('play', kick);
    video.addEventListener('pause', stopLoop);
    document.addEventListener('visibilitychange', onVisibility);
    // Initial paint; the loop only starts if already playing.
    kick();
    return () => {
      stopLoop();
      video.removeEventListener('seeked', onSeek);
      video.removeEventListener('loadeddata', onData);
      video.removeEventListener('canplay', paint);
      video.removeEventListener('error', onVideoError);
      video.removeEventListener('play', kick);
      video.removeEventListener('pause', stopLoop);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [objectUrl, draw, clearCanvases]);

  const inBounds =
    !frameSize ||
    (frameSize.w >= MODEL_INPUT.x + MODEL_INPUT.w &&
      frameSize.h >= MODEL_INPUT.y + MODEL_INPUT.h);

  const retry = () => {
    const video = videoRef.current;
    if (!video) {
      // No source element (rejected URL): stay on the error UI.
      setStatus('error');
      return;
    }
    setStatus('loading');
    clearCanvases();
    try {
      video?.load();
    } catch {
      setStatus('error');
    }
  };

  return (
    <div className="rounded-lg bg-surface-2 p-3">
      {/* Hidden source video: same bytes as the selected video. */}
      {safeSrc ? (
        <video
          ref={videoRef}
          src={safeSrc}
          preload="auto"
          muted
          playsInline
          aria-hidden="true"
          className="hidden"
        />
      ) : null}

      {!inBounds && (
        <p className="mb-2 text-xs text-warning leading-relaxed" role="note">
          This frame is smaller than the fixed {MODEL_INPUT.w}×{MODEL_INPUT.h} crop
          region — model input may be invalid for this video.
        </p>
      )}

      <div className="relative">
        <div className={mode === 'crop' ? 'hidden' : 'min-w-0'}>
          <p className="text-xs text-foreground/65 mb-1 flex items-center gap-1">
            <ScanEye size={12} /> Original Frame
          </p>
          <canvas
            ref={frameRef}
            role="img"
            className="mx-auto w-auto max-w-full max-h-[300px] rounded-lg bg-black"
            aria-label="Original video frame with model input region overlay"
          />
        </div>
        <div className={mode === 'crop' ? '' : 'hidden'}>
          <p className="text-xs text-foreground/65 mb-1 flex items-center gap-1">
            <Crop size={12} /> Model Input
          </p>
          <canvas
            ref={cropRef}
            role="img"
            width={MODEL_INPUT.w}
            height={MODEL_INPUT.h}
            style={{ imageRendering: 'pixelated' }}
            className="rounded-lg bg-black w-full h-auto border border-border"
            aria-label="Grayscale model input crop, 140 by 46 pixels"
          />
          <p className="text-xs text-foreground/65 mt-1 text-center sm:text-left">
            {MODEL_INPUT.w}×{MODEL_INPUT.h} · grayscale
          </p>
        </div>
        {status !== 'ready' && (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-lg bg-black/70 px-4 text-center"
            role={status === 'error' ? 'alert' : 'status'}
          >
            {status === 'loading' ? (
              <>
                <LoaderIcon size={20} animate className="text-white" />
                <p className="text-xs font-medium text-white">Preparing model input…</p>
              </>
            ) : (
              <>
                <p className="text-xs font-medium text-white">Could not load video frames.</p>
                <button
                  type="button"
                  onClick={retry}
                  className="rounded-md border border-white/30 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-white/10"
                >
                  Retry
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
