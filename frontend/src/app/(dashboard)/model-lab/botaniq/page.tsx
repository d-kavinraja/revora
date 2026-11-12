'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { botaniqApi } from '@/lib/api';
import type { BotaniQConfig, BotaniQHistoryItem, BotaniQInferenceResult, BotaniQSampleImage } from '@/lib/api';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';
import { SkeletonList } from '@/components/shared/skeleton';
import { MultiStepLoader } from '@/components/ui/multi-step-loader';
import type { LoaderStage } from '@/components/ui/multi-step-loader';
import { BotaniQHero } from './_components/BotaniQHero';
import { UploadCard } from './_components/UploadCard';
import { ResultsPanel } from './_components/ResultsPanel';
import { FinalResultCard } from './_components/FinalResultCard';
import { Top5Card } from './_components/Top5Card';
import { HistoryTable } from './_components/HistoryTable';
import type { Phase, SelectedImage, InputTab } from './_components/types';
import { friendlyError } from './_components/types';

export default function BotaniQPage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'botaniq');
  if (status !== 'enabled') {
    return (
      <div className="w-full min-w-0 max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable status={status} message={message} title="BotaniQ is unavailable" variant="page" />
      </div>
    );
  }
  return <BotaniQLab />;
}

function BotaniQLab() {
  const [config, setConfig] = useState<BotaniQConfig | null>(null);
  const [history, setHistory] = useState<BotaniQHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [inputTab, setInputTab] = useState<InputTab>('upload');
  const [selected, setSelected] = useState<SelectedImage | null>(null);
  const [urlInput, setUrlInput] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [uploadPct, setUploadPct] = useState(0);
  const [result, setResult] = useState<BotaniQInferenceResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedS, setElapsedS] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.allSettled([
      botaniqApi.getConfig(),
      botaniqApi.getDataset(),
      botaniqApi.getHistory(20, 0),
    ]).then(([c, d, h]) => {
      if (!alive) return;
      if (c.status === 'fulfilled') setConfig(c.value);
      if (d.status === 'fulfilled') {}
      if (h.status === 'fulfilled') setHistory(h.value);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (phase === 'warming' || phase === 'uploading' || phase === 'processing') {
      timerRef.current = window.setInterval(() => setElapsedS((s) => s + 1), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [phase]);

const pickDatasetImage = useCallback(
    async (img: BotaniQSampleImage): Promise<SelectedImage | null> => {
      setError(null);
      setResult(null);
      try {
        const blob = await botaniqApi.getDatasetBlob(img.id);
        const objectUrl = URL.createObjectURL(blob);
        if (selected?.objectUrl && selected.objectUrl.startsWith('blob:')) {
          URL.revokeObjectURL(selected.objectUrl);
        }
        const sel: SelectedImage = {
          kind: 'dataset',
          filename: img.filename,
          blob,
          objectUrl,
          sizeBytes: img.size_bytes ?? blob.size,
          testImageId: img.id,
          label: img.plant_name ? `${img.plant_name}${img.plant_type ? ` (${img.plant_type})` : ''}` : img.label,
        };
        setSelected(sel);
        setPhase('idle');
        return sel;
      } catch (err) {
        setError('Could not load sample image: ' + friendlyError(err));
        setPhase('failed');
        return null;
      }
    },
    [selected],
  );

  const acceptFile = useCallback(
    (file: File | null) => {
      if (!file) return;
      if (selected?.objectUrl && selected.kind === 'upload') URL.revokeObjectURL(selected.objectUrl);
      setSelected({
        kind: 'upload',
        filename: file.name,
        blob: file,
        objectUrl: URL.createObjectURL(file),
        sizeBytes: file.size,
      });
      setResult(null);
      setError(null);
      setPhase('idle');
    },
    [selected],
  );

  const commitUrl = useCallback(() => {
    const u = urlInput.trim();
    if (!u) return;
    if (!/^https?:\/\//i.test(u)) {
      setError('Only http and https URLs are supported.');
      return;
    }
    if (selected?.objectUrl && selected.kind === 'upload') URL.revokeObjectURL(selected.objectUrl);
    setSelected({ kind: 'url', filename: u.split('?')[0].split('/').pop() || 'image.jpg', objectUrl: u, sizeBytes: null });
    setResult(null);
    setError(null);
    setPhase('idle');
  }, [urlInput, selected]);

  const run = useCallback(async () => {
    if (!selected || phase === 'warming' || phase === 'uploading' || phase === 'processing') return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setResult(null);
    setError(null);
    setUploadPct(0);
    setElapsedS(0);
    setPhase('warming');

    try {
      await botaniqApi.warm({ signal: ctrl.signal });
      setPhase('uploading');

      let res: BotaniQInferenceResult;
      if (selected.kind === 'url') {
        setPhase('processing');
        res = await botaniqApi.runInferenceUrl(selected.objectUrl, { signal: ctrl.signal });
      } else {
        let blob = selected.blob;
        if (!blob) {
          if (selected.testImageId) {
            blob = await botaniqApi.getDatasetBlob(selected.testImageId);
          } else {
            blob = await fetch(selected.objectUrl).then((r) => r.blob());
          }
        }
        if (!blob) throw new Error('Could not read image data');
        res = await botaniqApi.runInference(
          blob,
          selected.filename,
          {
            test_image_id: selected.testImageId,
            source: selected.kind === 'dataset' ? 'test' : 'upload',
            signal: ctrl.signal,
          },
          (pct, done) => {
            setUploadPct(pct);
            if (done) setPhase('processing');
          },
        );
      }

      setResult(res);
      setPhase('completed');
      botaniqApi.getHistory(20, 0).then(setHistory).catch(() => {});
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError' || (err as { code?: string })?.code === 'ERR_CANCELED') return;
      setError(friendlyError(err));
      setPhase('failed');
    }
  }, [selected, phase]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setPhase('idle');
    setError(null);
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    if (selected?.objectUrl && selected.kind === 'upload') URL.revokeObjectURL(selected.objectUrl);
    setSelected(null);
    setResult(null);
    setError(null);
    setPhase('idle');
    setUploadPct(0);
    setUrlInput('');
  }, [selected]);

  const busy = phase === 'warming' || phase === 'uploading' || phase === 'processing';
  const canRun = !!selected && !busy;

  const loaderStages: LoaderStage[] =
    phase === 'warming'
      ? [
          { id: 'warming', label: 'Warming up model', status: 'active', detail: 'Starting the inference service…' },
          { id: 'uploading', label: 'Uploading image', status: 'pending' },
          { id: 'processing', label: 'Running inference', status: 'pending' },
        ]
      : phase === 'uploading'
        ? [
            { id: 'warming', label: 'Warming up model', status: 'done', detail: 'Model ready' },
            { id: 'uploading', label: 'Uploading image', status: 'active', detail: uploadPct > 0 ? `${uploadPct}% uploaded` : 'Sending image…' },
            { id: 'processing', label: 'Running inference', status: 'pending' },
          ]
        : phase === 'processing'
          ? [
              { id: 'warming', label: 'Warming up model', status: 'done', detail: 'Model ready' },
              { id: 'uploading', label: 'Uploading image', status: 'done', detail: 'Upload complete' },
              { id: 'processing', label: 'Running inference', status: 'active', detail: 'Model is processing on the backend…' },
            ]
          : [
              { id: 'warming', label: 'Warming up model', status: 'pending' },
              { id: 'uploading', label: 'Uploading image', status: 'pending' },
              { id: 'processing', label: 'Running inference', status: 'pending' },
            ];

  const loaderOpen = busy;

  return (
    <div className="w-full min-w-0 max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 space-y-5 md:space-y-6 overflow-x-clip">
      <BotaniQHero />

      {loading ? (
        <SkeletonList />
      ) : (
        <>
<div className="grid gap-4 md:gap-5 md:grid-cols-2">
            <div id="model-lab-upload" className="scroll-mt-4 h-[560px] min-w-0">
              <UploadCard
                config={config}
                tab={inputTab}
                onTabChange={setInputTab}
                onFile={acceptFile}
                urlInput={urlInput}
                onUrlChange={setUrlInput}
                onCommitUrl={commitUrl}
                selected={selected}
                onClear={reset}
                onRun={run}
                canRun={canRun}
                busy={busy}
                onSelectDataset={pickDatasetImage}
              />
            </div>
            <div className="h-[560px] min-w-0">
              <ResultsPanel
                selected={selected}
                phase={phase}
                uploadPct={uploadPct}
                error={error}
                busy={busy}
                canRun={canRun}
                failed={phase === 'failed'}
                onRun={run}
                onClear={reset}
              />
            </div>
          </div>

          {result && phase === 'completed' && (
            <div className="grid gap-4 md:gap-5 md:grid-cols-2">
              <div className="min-w-0">
                <FinalResultCard result={result} />
              </div>
              <div className="min-w-0">
                <Top5Card result={result} />
              </div>
            </div>
          )}

          {history.length > 0 && <HistoryTable history={history} />}
        </>
      )}

      <MultiStepLoader
        open={loaderOpen}
        stages={loaderStages}
        title="Running BotaniQ inference"
        subtitle={selected?.filename ?? null}
        uploadPct={phase === 'uploading' ? uploadPct : null}
        elapsedS={elapsedS}
        onCancel={cancel}
      />
    </div>
  );
}