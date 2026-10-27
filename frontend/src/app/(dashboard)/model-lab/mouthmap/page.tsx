'use client';

import { useEffect, useRef, useState } from 'react';
import { apiClient, mouthmapApi } from '@/lib/api';
import type {
  MouthMapConfig,
  MouthMapHistoryItem,
  MouthMapInferenceResult,
  MouthMapTestVideo,
} from '@/lib/api';
import { useToast } from '@/components/ui/toaster';
import { SkeletonList } from '@/components/shared/skeleton';
import { MultiStepLoader } from '@/components/ui/multi-step-loader';
import type { LoaderStage } from '@/components/ui/multi-step-loader';
import { ModelLabHero } from './_components/ModelLabHero';
import { UploadCard } from './_components/UploadCard';
import { DatasetCard } from './_components/DatasetCard';
import { AnalysisSection } from './_components/AnalysisSection';
import { HistoryTable } from './_components/HistoryTable';
import type { Phase, SelectedVideo, UploadMode } from './_components/types';
import { friendlyError } from './_components/types';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';

// Gate at the route level so none of the lab's fetch effects run while
// `mouthmap` is disabled (all mouthmap routes 503 server-side; mounting the
// child would only produce failed requests behind a cosmetic overlay).
export default function MouthMapPage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'mouthmap');

  if (status !== 'enabled') {
    return (
      <div className="w-full min-w-0 max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable status={status} message={message} title="MouthMap is unavailable" />
      </div>
    );
  }

  return <MouthMapLab />;
}

function MouthMapLab() {
  const { toast } = useToast();
  const [config, setConfig] = useState<MouthMapConfig | null>(null);
  const [dataset, setDataset] = useState<MouthMapTestVideo[]>([]);
  const [history, setHistory] = useState<MouthMapHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadMode, setUploadMode] = useState<UploadMode>('upload');
  const [selected, setSelected] = useState<SelectedVideo | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [uploadPct, setUploadPct] = useState(0);
  // Set ONLY when an XHR progress event reports loaded >= total — never
  // inferred from elapsed time. Distinguishes "bytes in flight" from
  // "upload delivered, backend computing".
  const [uploadDone, setUploadDone] = useState(false);
  const [result, setResult] = useState<MouthMapInferenceResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedS, setElapsedS] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  // Monotonic id for dataset picks: a late response from an earlier click
  // must never overwrite (or revoke the URL of) a newer selection.
  const pickSeqRef = useRef(0);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [durations, setDurations] = useState<Record<string, number | null>>({});

  // Recording state
  const [recording, setRecording] = useState(false);
  const [recSecs, setRecSecs] = useState(0);
  const [camStream, setCamStream] = useState<MediaStream | null>(null);
  const liveRef = useRef<HTMLVideoElement | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);

  const readDuration = (url: string): Promise<number | null> =>
    new Promise((resolve) => {
      const el = document.createElement('video');
      el.preload = 'metadata';
      el.muted = true;
      const done = (v: number | null) => {
        el.src = '';
        resolve(v);
      };
      el.onloadedmetadata = () =>
        done(Number.isFinite(el.duration) ? el.duration : null);
      el.onerror = () => done(null);
      window.setTimeout(() => done(null), 8000);
      el.src = url;
    });

  async function prefetchThumbs(videos: MouthMapTestVideo[]) {
    const MAX_THUMB_BYTES = 8 * 1024 * 1024;
    const CONCURRENCY = 4;
    const fetchOne = async (v: MouthMapTestVideo) => {
      if (v.size_bytes && v.size_bytes > MAX_THUMB_BYTES) return null;
      const res = await apiClient.get(
        `/mouthmap/dataset/${encodeURIComponent(v.id)}/stream`,
        { responseType: 'blob' },
      );
      const blob = res.data as Blob;
      if (!blob || blob.size === 0) return null;
      const url = URL.createObjectURL(blob);
      const dur = await readDuration(url);
      return { id: v.id, url, dur };
    };
    const settled: PromiseSettledResult<{ id: string; url: string; dur: number | null } | null>[] = [];
    for (let i = 0; i < videos.length; i += CONCURRENCY) {
      const batch = await Promise.allSettled(videos.slice(i, i + CONCURRENCY).map(fetchOne));
      settled.push(...batch);
    }
    const t: Record<string, string> = {};
    const d: Record<string, number | null> = {};
    for (const r of settled) {
      if (r.status === 'fulfilled' && r.value) {
        t[r.value.id] = r.value.url;
        d[r.value.id] = r.value.dur;
      }
    }
    setThumbs((prev) => {
      Object.values(prev).forEach((u) => {
        if (u.startsWith('blob:') && !Object.values(t).includes(u)) URL.revokeObjectURL(u);
      });
      return t;
    });
    setDurations(d);
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [cfg, ds, hist] = await Promise.all([
          mouthmapApi.getConfig(),
          mouthmapApi.getDataset().catch(() => [] as MouthMapTestVideo[]),
          mouthmapApi.getHistory().catch(() => [] as MouthMapHistoryItem[]),
        ]);
        if (cancelled) return;
        setConfig(cfg);
        setDataset(ds);
        setHistory(hist);
        // Prefetch small dataset videos (auth fetch -> blob URLs) for REAL
        // thumbnails. Large files fall back to the icon tile. Durations are
        // read from actual video metadata — never fabricated.
        if (!cancelled && ds.length > 0) {
          void prefetchThumbs(ds);
        }
      } catch (e) {
        if (!cancelled)
          toast({
            title: 'Failed to load Model Lab',
            description: friendlyError(e),
            type: 'error',
          });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast]);

  useEffect(() => {
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      camStream?.getTracks().forEach((t) => t.stop());
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Live elapsed-time ticker — display only, never drives stage completion.
  useEffect(() => {
    if (
      phase !== 'warming' &&
      phase !== 'uploading' &&
      phase !== 'processing' &&
      phase !== 'preparing'
    )
      return;
    const t = window.setInterval(() => setElapsedS((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [phase]);

  useEffect(() => {
    return () => {
      setThumbs((prev) => {
        Object.values(prev).forEach((u) => {
          if (u.startsWith('blob:')) URL.revokeObjectURL(u);
        });
        return prev;
      });
    };
  }, []);

  const setSelectedVideo = (v: SelectedVideo | null) => {
    setSelected((prev) => {
      if (prev && prev.objectUrl.startsWith('blob:') && prev !== v) {
        URL.revokeObjectURL(prev.objectUrl);
      }
      return v;
    });
  };

  const pickDatasetVideo = async (v: MouthMapTestVideo): Promise<SelectedVideo | null> => {
    setError(null);
    setResult(null);
    setPhase('preparing');
    const seq = (pickSeqRef.current += 1);
    try {
      const res = await apiClient.get(
        `/mouthmap/dataset/${encodeURIComponent(v.id)}/stream`,
        { responseType: 'blob' },
      );
      // A newer pick started while this fetch was in flight: drop this
      // response (no object URL was created yet, so nothing leaks) and
      // never let Video A's late arrival overwrite Video B's preview.
      if (seq !== pickSeqRef.current) return null;
      const blob = res.data as Blob;
      const url = URL.createObjectURL(blob);
      const sel: SelectedVideo = {
        kind: 'dataset',
        filename: v.filename,
        blob,
        objectUrl: url,
        sizeBytes: v.size_bytes ?? blob.size,
        testVideoId: v.id,
        expected: v.ground_truth,
      };
      setSelectedVideo(sel);
      setPhase('idle');
      document
        .getElementById('model-lab-analysis')
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return sel;
    } catch (e) {
      // A superseded pick's failure must not surface as the new
      // selection's error.
      if (seq !== pickSeqRef.current) return null;
      setPhase('failed');
      setError(friendlyError(e));
      return null;
    }
  };

  const acceptFile = (f: File | undefined | null) => {
    if (!f) return;
    setError(null);
    setResult(null);
    const ext = `.${(f.name.split('.').pop() ?? '').toLowerCase()}`;
    const allowed = (config?.allowed_extensions ?? ['.mp4', '.webm', '.mpg']).map((a) =>
      a.toLowerCase(),
    );
    if (!allowed.includes(ext)) {
      setError(
        `Video format is not supported. Supported formats: ${allowed.join(', ').toUpperCase()}`,
      );
      return;
    }
    const maxBytes = (config?.max_upload_mb ?? 50) * 1024 * 1024;
    if (f.size > maxBytes) {
      setError(`Video is too large. Maximum size is ${config?.max_upload_mb ?? 50} MB.`);
      return;
    }
    const url = URL.createObjectURL(f);
    setSelectedVideo({
      kind: uploadMode === 'record' ? 'record' : 'upload',
      filename: f.name,
      blob: f,
      objectUrl: url,
      sizeBytes: f.size,
    });
    setPhase('idle');
  };

  const startCamera = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      setCamStream(stream);
      requestAnimationFrame(() => {
        if (liveRef.current) liveRef.current.srcObject = stream;
      });
    } catch {
      setError('Camera/microphone permission was denied. Allow access to record video.');
    }
  };

  const stopCamera = () => {
    camStream?.getTracks().forEach((t) => t.stop());
    setCamStream(null);
  };

  const startRecording = () => {
    if (!camStream) return;
    const mimeCandidates = [
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm',
      'video/mp4',
    ];
    const mime =
      mimeCandidates.find((m) => window.MediaRecorder?.isTypeSupported(m)) ?? '';
    const rec = mime ? new MediaRecorder(camStream, { mimeType: mime }) : new MediaRecorder(camStream);
    chunksRef.current = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) chunksRef.current.push(e.data);
    };
    rec.onstop = () => {
      const type = rec.mimeType || 'video/webm';
      const blob = new Blob(chunksRef.current, { type });
      const ext = type.includes('mp4') ? 'mp4' : 'webm';
      const url = URL.createObjectURL(blob);
      setSelectedVideo({
        kind: 'record',
        filename: `recording-${new Date().toISOString().replace(/[:.]/g, '-')}.${ext}`,
        blob,
        objectUrl: url,
        sizeBytes: blob.size,
      });
      stopCamera();
    };
    recorderRef.current = rec;
    rec.start();
    setRecording(true);
    setRecSecs(0);
    timerRef.current = window.setInterval(() => setRecSecs((s) => s + 1), 1000);
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    setRecording(false);
    if (timerRef.current) window.clearInterval(timerRef.current);
  };

  const runInference = async (sel: SelectedVideo | null = selected) => {
    if (!sel?.blob) return;
    // Prevent duplicate jobs from double-clicks or overlapping triggers.
    if (running || phase === 'preparing') return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setError(null);
    setResult(null);
    setUploadPct(0);
    setUploadDone(false);
    setElapsedS(0);

    // On-demand wake-up: ask the backend to bring the hosted HF Space up and
    // confirm readiness BEFORE uploading the video. The backend holds this
    // request while the Space boots (bounded by MOUTHMAP_WAKE_TIMEOUT_S), so
    // an idle Space is never woken by page loads — only by starting a run.
    setPhase('warming');
    try {
      await mouthmapApi.warm({ signal: controller.signal });
    } catch (e) {
      if (controller.signal.aborted) {
        setPhase('idle');
        toast({ title: 'Inference cancelled', description: 'The request was cancelled. No result was produced.', type: 'info' });
        return;
      }
      setPhase('failed');
      setError(friendlyError(e));
      return;
    }
    if (controller.signal.aborted) {
      setPhase('idle');
      toast({ title: 'Inference cancelled', description: 'The request was cancelled. No result was produced.', type: 'info' });
      return;
    }

    setPhase('uploading');
    try {
      setPhase('processing');
      const out = await mouthmapApi.runInference(
        sel.blob,
        sel.filename,
        {
          test_video_id: sel.testVideoId,
          source: sel.kind === 'dataset' ? 'test' : sel.kind,
          signal: controller.signal,
        },
        (p, done) => {
          setPhase('uploading');
          setUploadPct(p);
          if (done) setUploadDone(true);
        },
      );
      if (controller.signal.aborted) return;
      setResult(out);
      setPhase('completed');
      toast({ title: 'Inference completed', description: out.prediction, type: 'success' });
      mouthmapApi.getHistory().then(setHistory).catch(() => {});
    } catch (e) {
      if (controller.signal.aborted) {
        setPhase('idle');
        setUploadPct(0);
        toast({ title: 'Inference cancelled', description: 'The request was cancelled. No result was produced.', type: 'info' });
        return;
      }
      setPhase('failed');
      setError(friendlyError(e));
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  };

  const cancelInference = () => {
    abortRef.current?.abort();
  };

  const selectAndRun = async (v: MouthMapTestVideo) => {
    if (running || phase === 'preparing') return;
    const sel = await pickDatasetVideo(v);
    if (sel) {
      document
        .getElementById('model-lab-analysis')
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      await runInference(sel);
    }
  };

  const rerunHistory = (h: MouthMapHistoryItem) => {
    const v = dataset.find(
      (d) => d.id === h.test_video_id || d.filename === h.video_filename,
    );
    if (v) selectAndRun(v);
  };

  const viewHistory = (h: MouthMapHistoryItem) => {
    const match =
      h.is_match === null || h.is_match === undefined
        ? 'no ground truth'
        : h.is_match
          ? 'Correct'
          : 'Mismatch';
    toast({
      title: h.video_filename,
      description: `Prediction: ${h.prediction ?? '—'} · Expected: ${h.expected ?? '—'} · ${match}`,
      type: h.status === 'completed' ? 'success' : 'error',
    });
  };

  const clearSelection = () => {
    setSelectedVideo(null);
    setResult(null);
    setError(null);
    setPhase('idle');
  };

  const handleAddVideo = () => {
    setUploadMode('upload');
    document
      .getElementById('model-lab-upload')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const handleMetadata = (durationS: number | null, resolution: string | null) => {
    setSelected((s) =>
      s ? { ...s, durationS: durationS ?? s.durationS, resolution: resolution ?? s.resolution } : s,
    );
  };

  const statusLabel =
    phase === 'warming'
      ? 'Waking up model...'
      : phase === 'uploading' && !uploadDone
        ? `Uploading video... ${uploadPct}%`
        : phase === 'preparing'
          ? 'Preparing video...'
          : phase === 'processing' || (phase === 'uploading' && uploadDone)
            ? 'Running MouthMap inference...'
            : phase === 'completed'
              ? 'Inference completed.'
              : null;

  const running =
    phase === 'warming' || phase === 'uploading' || phase === 'processing';
  const canRun = !!selected?.blob && !running && phase !== 'preparing';

  // Honest live stages with exactly ONE active stage at a time:
  // - Wake-up is its own stage, shown only while the backend confirms it is
  //   bringing the hosted model up before the video is uploaded.
  // - Upload is done ONLY on an observed XHR loaded >= total event.
  // - Inference is pending until uploadDone, active after — never while
  //   merely waiting for bytes to finish sending.
  // - Backend-internal steps (model load, frame processing) stay merged:
  //   the API exposes no per-stage progress, and elapsed time never
  //   completes a stage.
  const loaderStages: LoaderStage[] =
    phase === 'warming'
      ? [
          { id: 'wake', label: 'Waking up model', status: 'active', detail: 'Starting the inference service…' },
          { id: 'upload', label: 'Uploading video', status: 'pending' },
          { id: 'inference', label: 'Running inference', status: 'pending' },
        ]
      : phase === 'preparing'
        ? [
            { id: 'prepare', label: 'Preparing video', status: 'active', detail: 'Downloading test video…' },
            { id: 'upload', label: 'Uploading video', status: 'pending' },
            { id: 'inference', label: 'Running inference', status: 'pending' },
          ]
        : [
            { id: 'prepare', label: 'Preparing video', status: 'done', detail: 'Video validated' },
            uploadDone
              ? { id: 'upload', label: 'Uploading video', status: 'done', detail: 'Upload complete' }
              : {
                  id: 'upload',
                  label: 'Uploading video',
                  status: 'active',
                  detail: uploadPct > 0 ? `${uploadPct}% uploaded` : 'Sending video…',
                },
            uploadDone
              ? {
                  id: 'inference',
                  label: 'Running inference',
                  status: 'active',
                  detail: 'Model is processing on the backend…',
                }
              : { id: 'inference', label: 'Running inference', status: 'pending' },
          ];

  const loaderOpen = running || phase === 'preparing';

  return (
    <div className="w-full min-w-0 max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 space-y-5 md:space-y-6 overflow-x-clip">
      <ModelLabHero />

      {loading ? (
        <SkeletonList />
      ) : (
        <>
          <div className="grid gap-4 md:gap-5 md:grid-cols-2">
            <div id="model-lab-upload" className="scroll-mt-4 h-full min-w-0">
              <UploadCard
                config={config}
                mode={uploadMode}
                onModeChange={setUploadMode}
                onFile={acceptFile}
                selected={selected}
                onRemove={clearSelection}
                error={error}
                camActive={!!camStream}
                recording={recording}
                recSecs={recSecs}
                liveRef={liveRef}
                onEnableCamera={startCamera}
                onCancelCamera={stopCamera}
                onStartRecording={startRecording}
                onStopRecording={stopRecording}
              />
            </div>
            <div className="h-full min-w-0">
              <DatasetCard
                dataset={dataset}
                selectedId={selected?.testVideoId}
                phase={phase}
                thumbs={thumbs}
                durations={durations}
                onSelect={pickDatasetVideo}
                onRun={selectAndRun}
                onAddVideo={handleAddVideo}
                busy={running || phase === 'preparing'}
              />
            </div>
          </div>

          <div id="model-lab-analysis" className="scroll-mt-4 min-w-0">
            <AnalysisSection
              selected={selected}
              phase={phase}
              uploadPct={uploadPct}
              result={result}
              error={error}
              statusLabel={statusLabel}
              canRun={canRun}
              running={running}
              failed={phase === 'failed'}
              onRun={() => runInference()}
              onRemove={clearSelection}
              onMetadata={handleMetadata}
            />
          </div>

          <HistoryTable history={history} onRerun={rerunHistory} onView={viewHistory} />
        </>
      )}

      <MultiStepLoader
        open={loaderOpen}
        stages={loaderStages}
        title="Running MouthMap inference"
        subtitle={selected?.filename ?? null}
        uploadPct={phase === 'uploading' ? uploadPct : null}
        elapsedS={elapsedS}
        onCancel={cancelInference}
      />
    </div>
  );
}
