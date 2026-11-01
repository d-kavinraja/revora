'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Database,
  ExternalLink,
  FlaskConical,
  History,
  Image as ImageIcon,
  Leaf,
  Link2,
  Loader2,
  RefreshCcw,
  Search,
  Settings2,
  Trophy,
  Upload,
  X,
} from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { botaniqApi } from '@/lib/api';
import type {
  BotaniQConfig,
  BotaniQHistoryItem,
  BotaniQInferenceResult,
  BotaniQSampleImage,
} from '@/lib/api';
import { useToast } from '@/components/ui/toaster';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';

// ─── Types ───────────────────────────────────────────────────────────────────

type Phase = 'idle' | 'warming' | 'uploading' | 'processing' | 'completed' | 'failed';
type InputTab = 'upload' | 'url' | 'dataset';

interface SelectedImage {
  kind: 'upload' | 'url' | 'dataset';
  filename: string;
  blob?: Blob;
  objectUrl: string;
  sizeBytes?: number | null;
  testImageId?: string;
  label?: string | null;
}

function fmtBytes(n?: number | null) {
  if (n == null) return 'N/A';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function friendlyError(err: unknown): string {
  const e = err as { code?: string; message?: string; response?: { status?: number; data?: { detail?: unknown } } };
  const code = typeof e?.code === 'string' ? e.code : '';
  const status = typeof e?.response?.status === 'number' ? e.response.status : null;
  if (code === 'ERR_NETWORK') return 'Cannot reach the backend server. Check that the API is running.';
  if (code === 'ECONNABORTED') return 'Inference request timed out. Please try again.';
  if (status === 401) return 'Your session has expired. Please sign in again.';
  if (status === 429) return 'Too many requests. Please wait a moment and try again.';
  const rawDetail = e?.response?.data?.detail;
  const detail = Array.isArray(rawDetail)
    ? rawDetail.map((d) => (typeof d === 'object' && d !== null ? String((d as { msg?: unknown }).msg ?? '') : String(d))).filter(Boolean).join(' ')
    : ((rawDetail as string | undefined) ?? (err as Error)?.message ?? '');
  if (/too large|maximum size/i.test(detail)) return detail;
  if (/timed out|timeout|504/i.test(detail)) return 'Inference timed out. Please try again.';
  if (/waking up|did not finish waking/i.test(detail)) return detail;
  if (/unavailable|502|503/i.test(detail)) return 'BotaniQ inference service is currently unavailable. Please try again later.';
  if (/could not fetch|publicly accessible/i.test(detail)) return detail;
  if (/not supported|unsupported/i.test(detail)) return detail;
  return detail || 'Something went wrong. Please try again.';
}

// ─── Feature gate ─────────────────────────────────────────────────────────────

export default function BotaniQPage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'botaniq');
  if (status !== 'enabled') {
    return (
      <div className="w-full min-w-0 max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable status={status} message={message} title="BotaniQ is unavailable" />
      </div>
    );
  }
  return <BotaniQLab />;
}

// ─── Main lab ────────────────────────────────────────────────────────────────

function BotaniQLab() {
  const { toast } = useToast();
  const reduce = useReducedMotion();

  const [config, setConfig] = useState<BotaniQConfig | null>(null);
  const [dataset, setDataset] = useState<BotaniQSampleImage[]>([]);
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
  const [showRaw, setShowRaw] = useState(false);
  const [datasetFilter, setDatasetFilter] = useState('');

  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Boot: load config + dataset + history ──────────────────────────────
  useEffect(() => {
    let alive = true;
    Promise.allSettled([
      botaniqApi.getConfig(),
      botaniqApi.getDataset(),
      botaniqApi.getHistory(20, 0),
    ]).then(([c, d, h]) => {
      if (!alive) return;
      if (c.status === 'fulfilled') setConfig(c.value);
      if (d.status === 'fulfilled') setDataset(d.value);
      if (h.status === 'fulfilled') setHistory(h.value);
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  // ── Elapsed timer ───────────────────────────────────────────────────────
  useEffect(() => {
    if (phase === 'warming' || phase === 'uploading' || phase === 'processing') {
      timerRef.current = window.setInterval(() => setElapsedS((s) => s + 1), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [phase]);

  // ── File picker ─────────────────────────────────────────────────────────
  const onFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (selected?.objectUrl) URL.revokeObjectURL(selected.objectUrl);
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
  }, [selected]);

  // ── Drag + drop ─────────────────────────────────────────────────────────
  const onDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (selected?.objectUrl) URL.revokeObjectURL(selected.objectUrl);
    setSelected({
      kind: 'upload',
      filename: file.name,
      blob: file,
      objectUrl: URL.createObjectURL(file),
      sizeBytes: file.size,
    });
    setResult(null); setError(null); setPhase('idle');
  }, [selected]);

  // ── Dataset pick ─────────────────────────────────────────────────────────
  const pickDatasetImage = useCallback(async (img: BotaniQSampleImage) => {
    setError(null);
    setResult(null);
    try {
      const blob = await botaniqApi.getDatasetBlob(img.id);
      const objectUrl = URL.createObjectURL(blob);
      if (selected?.objectUrl && selected.objectUrl.startsWith('blob:')) {
        URL.revokeObjectURL(selected.objectUrl);
      }
      setSelected({
        kind: 'dataset',
        filename: img.filename,
        blob,
        objectUrl,
        sizeBytes: img.size_bytes ?? blob.size,
        testImageId: img.id,
        label: img.plant_name ? `${img.plant_name}${img.plant_type ? ` (${img.plant_type})` : ''}` : img.label,
      });
      setPhase('idle');
      setInputTab('upload'); // switch to preview tab
    } catch (err) {
      setError('Could not load sample image: ' + friendlyError(err));
      setPhase('idle');
    }
  }, [selected]);

  // ── URL commit ───────────────────────────────────────────────────────────
  const commitUrl = useCallback(() => {
    const u = urlInput.trim();
    if (!u) return;
    if (!/^https?:\/\//i.test(u)) {
      setError('Only http and https URLs are supported.'); return;
    }
    if (selected?.objectUrl && selected.kind === 'upload') URL.revokeObjectURL(selected.objectUrl);
    setSelected({ kind: 'url', filename: u.split('?')[0].split('/').pop() || 'image.jpg', objectUrl: u, sizeBytes: null });
    setResult(null); setError(null); setPhase('idle');
  }, [urlInput, selected]);

  // ── Run ──────────────────────────────────────────────────────────────────
  const run = useCallback(async () => {
    if (!selected || phase === 'warming' || phase === 'uploading' || phase === 'processing') return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setResult(null); setError(null); setUploadPct(0); setElapsedS(0); setPhase('warming');

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
      // Refresh history
      botaniqApi.getHistory(20, 0).then(setHistory).catch(() => {});
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return;
      setError(friendlyError(err));
      setPhase('failed');
    }
  }, [selected, phase]);

  // ── Cancel ───────────────────────────────────────────────────────────────
  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setPhase('idle');
    setError(null);
  }, []);

  // ── Reset ────────────────────────────────────────────────────────────────
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
  const filteredDataset = dataset.filter((img) =>
    datasetFilter === '' ||
    img.filename.toLowerCase().includes(datasetFilter.toLowerCase()) ||
    (img.plant_name && img.plant_name.toLowerCase().includes(datasetFilter.toLowerCase()))
  );

  return (
    <div className="w-full min-w-0 max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 space-y-5 md:space-y-6">
      {/* Hero */}
      <motion.div
        initial={reduce ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <nav aria-label="Breadcrumb" className="text-xs text-foreground/60 mb-3">
          <Link href="/dashboard" className="hover:text-foreground transition-colors">Home</Link>
          <span className="mx-1.5" aria-hidden="true">&gt;</span>
          <Link href="/model-lab" className="hover:text-foreground transition-colors">Model Lab</Link>
          <span className="mx-1.5" aria-hidden="true">&gt;</span>
          <span aria-current="page" className="text-foreground font-medium">BotaniQ</span>
        </nav>

        <div className="rounded-xl border border-border p-5 md:p-7 bg-gradient-to-br from-emerald-950/30 via-surface-1 to-surface-1 relative overflow-hidden">
          {/* Decorative glow */}
          <div className="pointer-events-none absolute -top-16 -right-16 w-72 h-72 rounded-full bg-emerald-500/10 blur-3xl" aria-hidden="true" />
          <div className="flex flex-col lg:flex-row lg:items-center gap-6 relative">
            <div className="min-w-0 flex-1">
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight flex items-center gap-2 flex-wrap">
                <span className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-600 to-emerald-400 flex items-center justify-center text-white shrink-0 shadow-[0_0_20px_rgba(16,185,129,0.4)]">
                  <Leaf size={20} />
                </span>
                BotaniQ
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">v1</span>
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">Beta</span>
              </h1>
              <p className="text-foreground/75 text-sm mt-2 leading-relaxed max-w-[55ch]">
                Medicinal herb classifier — upload an image or paste a URL to identify plant and leaf species with confidence scores.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 lg:max-w-[440px] w-full">
              {[
                { icon: <ImageIcon size={16} />, label: 'Image Input', sub: 'Upload, URL, or dataset' },
                { icon: <Trophy size={16} />, label: 'Top-5 Results', sub: 'Ranked by confidence' },
                { icon: <FlaskConical size={16} />, label: 'VGG16 Model', sub: '224×224 RGB inference' },
              ].map(({ icon, label, sub }) => (
                <div key={label} className="flex sm:flex-col items-center sm:text-left gap-2.5 rounded-lg bg-surface-2 p-3">
                  <span className="shrink-0 w-9 h-9 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center">{icon}</span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold tracking-tight leading-tight">{label}</span>
                    <span className="block text-xs text-foreground/65 mt-0.5">{sub}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </motion.div>

      {/* 3-column workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-5">
        {/* Left: input panel */}
        <motion.div
          className="lg:col-span-1 space-y-4"
          initial={reduce ? false : { opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.35, delay: 0.06, ease: 'easeOut' }}
        >
          {/* Input tabs */}
          <div className="rounded-xl border border-border bg-surface-1 overflow-hidden">
            <div className="flex border-b border-border">
              {([['upload', 'Upload', <Upload key="u" size={13} />], ['url', 'URL', <Link2 key="l" size={13} />], ['dataset', 'Dataset', <Database key="d" size={13} />]] as const).map(([id, label, icon]) => (
                <button
                  key={id}
                  id={`botaniq-tab-${id}`}
                  onClick={() => setInputTab(id)}
                  className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-colors border-b-2 ${inputTab === id ? 'border-emerald-500 text-emerald-400 bg-emerald-500/5' : 'border-transparent text-foreground/60 hover:text-foreground'}`}
                  aria-selected={inputTab === id}
                  role="tab"
                >
                  {icon}{label}
                </button>
              ))}
            </div>

            <div className="p-4">
              {/* Upload tab */}
              {inputTab === 'upload' && (
                <div className="space-y-3">
                  <div
                    role="button"
                    tabIndex={0}
                    aria-label="Drop image here or click to browse"
                    onDrop={onDrop}
                    onDragOver={(e) => e.preventDefault()}
                    onClick={() => fileInputRef.current?.click()}
                    onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
                    className="border-2 border-dashed border-border rounded-xl p-6 text-center cursor-pointer hover:border-emerald-500/50 hover:bg-emerald-500/5 transition-all group"
                  >
                    <Upload size={24} className="mx-auto mb-2 text-foreground/40 group-hover:text-emerald-400 transition-colors" />
                    <p className="text-sm font-medium text-foreground/70">Drop image or click to browse</p>
                    <p className="text-xs text-foreground/45 mt-1">JPG · PNG · WebP · AVIF · GIF · Max {config?.max_upload_mb ?? 20} MB</p>
                    <input
                      ref={fileInputRef}
                      type="file"
                      id="botaniq-file-input"
                      accept=".jpg,.jpeg,.png,.webp,.avif,.gif,image/*"
                      className="sr-only"
                      onChange={onFileChange}
                    />
                  </div>
                  {selected && selected.kind === 'upload' && (
                    <ImagePreviewCard selected={selected} onClear={reset} />
                  )}
                </div>
              )}

              {/* URL tab */}
              {inputTab === 'url' && (
                <div className="space-y-3">
                  <label htmlFor="botaniq-url-input" className="block text-xs font-medium text-foreground/70 mb-1">Public image URL</label>
                  <div className="flex gap-2">
                    <input
                      id="botaniq-url-input"
                      type="url"
                      value={urlInput}
                      onChange={(e) => setUrlInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && commitUrl()}
                      placeholder="https://example.com/herb.jpg"
                      className="flex-1 text-sm px-3 py-2 rounded-lg border border-border bg-surface-2 text-foreground placeholder:text-foreground/40 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50"
                    />
                    <button
                      id="botaniq-url-confirm"
                      onClick={commitUrl}
                      disabled={!urlInput.trim()}
                      className="px-3 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      Set
                    </button>
                  </div>
                  <p className="text-[11px] text-foreground/50 leading-relaxed">
                    The backend fetches the URL server-side. Only publicly accessible images are supported. Private or auth-gated URLs will fail with a clear error.
                  </p>
                  {selected && selected.kind === 'url' && (
                    <ImagePreviewCard selected={selected} onClear={reset} />
                  )}
                </div>
              )}

              {/* Dataset tab */}
              {inputTab === 'dataset' && (
                <div className="space-y-3">
                  {loading ? (
                    <div className="flex items-center justify-center py-8 gap-2 text-foreground/50 text-sm">
                      <Loader2 size={16} className="animate-spin" />Loading dataset…
                    </div>
                  ) : dataset.length === 0 ? (
                    <div className="text-center py-8">
                      <Database size={28} className="mx-auto mb-2 text-foreground/30" />
                      <p className="text-sm text-foreground/60">No sample images yet</p>
                      <p className="text-xs text-foreground/45 mt-1">Drop images into <code className="bg-surface-2 px-1 rounded text-[11px]">backend/app/botaniq/dataset/</code></p>
                    </div>
                  ) : (
                    <>
                      <div className="relative">
                        <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-foreground/40" />
                        <input
                          id="botaniq-dataset-search"
                          type="text"
                          placeholder="Filter by name…"
                          value={datasetFilter}
                          onChange={(e) => setDatasetFilter(e.target.value)}
                          className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-border bg-surface-2 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                        />
                      </div>
                      <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                        {filteredDataset.map((img) => (
                          <button
                            key={img.id}
                            id={`botaniq-dataset-${img.id}`}
                            onClick={() => pickDatasetImage(img)}
                            className={`w-full text-left px-3 py-2 rounded-lg border transition-all text-sm ${selected?.testImageId === img.id ? 'border-emerald-500/60 bg-emerald-500/10 text-emerald-300' : 'border-border bg-surface-2 hover:border-emerald-500/30 hover:bg-emerald-500/5 text-foreground/80'}`}
                          >
                            <span className="font-medium block truncate">{img.plant_name ?? img.filename}</span>
                            {img.plant_type && <span className="text-[11px] text-foreground/50">{img.plant_type}</span>}
                            {img.size_bytes && <span className="text-[11px] text-foreground/40 ml-2">{fmtBytes(img.size_bytes)}</span>}
                          </button>
                        ))}
                        {filteredDataset.length === 0 && (
                          <p className="text-xs text-foreground/50 text-center py-4">No matches</p>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Run / Cancel button */}
          <button
            id="botaniq-run-btn"
            onClick={busy ? cancel : run}
            disabled={!selected && !busy}
            className={`w-full h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 ${busy ? 'bg-surface-2 border border-border text-foreground/70 hover:text-foreground' : 'bg-gradient-to-r from-emerald-600 to-emerald-500 text-white hover:brightness-110 hover:shadow-[0_0_20px_rgba(16,185,129,0.35)] active:scale-[0.99] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:brightness-100 disabled:hover:shadow-none'}`}
          >
            {busy ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                {phase === 'warming' ? `Waking model… ${elapsedS}s` : phase === 'uploading' ? `Uploading ${uploadPct}%` : `Running… ${elapsedS}s`}
                <span className="ml-1 text-xs opacity-70">(click to cancel)</span>
              </>
            ) : (
              <>
                <Leaf size={16} />
                {phase === 'completed' ? 'Run Again' : 'Identify Plant'}
              </>
            )}
          </button>

          {/* Config card */}
          <ConfigCard config={config} loading={loading} />
        </motion.div>

        {/* Right: results panel */}
        <motion.div
          className="lg:col-span-2 space-y-4"
          initial={reduce ? false : { opacity: 0, x: 8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.35, delay: 0.1, ease: 'easeOut' }}
        >
          {/* Error banner */}
          {phase === 'failed' && error && (
            <div id="botaniq-error-banner" className="flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
              <AlertCircle size={16} className="shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="font-medium">Inference failed</p>
                <p className="text-xs mt-0.5 opacity-80">{error}</p>
              </div>
              <button
                id="botaniq-retry-btn"
                onClick={run}
                disabled={!selected}
                className="shrink-0 flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-red-500/40 hover:bg-red-500/20 transition-colors disabled:opacity-40"
              >
                <RefreshCcw size={12} /> Retry
              </button>
            </div>
          )}

          {/* Image preview */}
          {selected && (
            <div className="rounded-xl border border-border bg-surface-1 overflow-hidden">
              <div className="px-4 py-3 border-b border-border flex items-center justify-between">
                <span className="text-sm font-medium flex items-center gap-1.5">
                  <ImageIcon size={14} className="text-emerald-400" />
                  {selected.kind === 'url' ? 'URL Image' : selected.kind === 'dataset' ? 'Test Image' : 'Uploaded Image'}
                </span>
                <span className="text-xs text-foreground/50 truncate max-w-[50%]">{selected.filename}</span>
              </div>
              <div className="relative bg-surface-2 flex items-center justify-center" style={{ minHeight: 220 }}>
                {/* Safe image rendering — only blob: and https: scheme */}
                {(selected.kind === 'upload' || selected.kind === 'dataset') ? (
                  <img
                    src={selected.objectUrl}
                    alt={selected.filename}
                    className="max-h-72 w-auto object-contain"
                    style={{ maxWidth: '100%' }}
                  />
                ) : (
                  /* URL images: show inline via <img> since user explicitly entered it */
                  <img
                    src={selected.objectUrl}
                    alt="Image from URL"
                    className="max-h-72 w-auto object-contain"
                    style={{ maxWidth: '100%' }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                )}
                {busy && (
                  <div className="absolute inset-0 bg-surface-1/70 backdrop-blur-sm flex flex-col items-center justify-center gap-2">
                    <Loader2 size={28} className="animate-spin text-emerald-400" />
                    <p className="text-sm font-medium text-foreground/80">
                      {phase === 'warming' ? 'Waking model…' : phase === 'uploading' ? `Uploading ${uploadPct}%` : 'Running inference…'}
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Results */}
          {result && phase === 'completed' && (
            <div className="space-y-4">
              {/* Top prediction card */}
              <div id="botaniq-result-card" className="rounded-xl border border-emerald-500/30 bg-gradient-to-br from-emerald-950/30 via-surface-1 to-surface-1 p-5">
                <div className="flex flex-col sm:flex-row sm:items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-foreground/50 uppercase tracking-widest mb-1">Identified as</p>
                    <h2 className="text-2xl md:text-3xl font-bold text-emerald-300 tracking-tight leading-tight">{result.prediction}</h2>
                    {result.plant_name && result.plant_type && (
                      <p className="text-sm text-foreground/60 mt-1">
                        <span className="font-medium text-foreground/80">{result.plant_name}</span>
                        {' · '}
                        <span className="px-1.5 py-0.5 rounded bg-surface-2 text-[11px] font-medium">{result.plant_type}</span>
                      </p>
                    )}
                  </div>
                  <div className="shrink-0 text-center">
                    <div className="text-4xl font-black tabular-nums text-emerald-400 leading-none">
                      {result.confidence != null ? `${result.confidence.toFixed(1)}%` : 'N/A'}
                    </div>
                    <p className="text-xs text-foreground/50 mt-1">Confidence</p>
                  </div>
                </div>

                {/* Metrics strip */}
                <div className="flex flex-wrap gap-3 mt-4 pt-4 border-t border-border/50">
                  <MetricChip icon={<Clock size={12} />} label="Inference" value={result.inference_time_ms != null ? `${result.inference_time_ms}ms` : 'N/A'} />
                  <MetricChip icon={<Settings2 size={12} />} label="Model" value={result.model} />
                  <MetricChip icon={<FlaskConical size={12} />} label="Classes" value={result.classes_available != null ? String(result.classes_available) : 'N/A'} />
                  {result.model_version && <MetricChip icon={<FlaskConical size={12} />} label="Version" value={result.model_version} />}
                </div>
              </div>

              {/* Top-5 predictions */}
              {result.top_5_predictions && result.top_5_predictions.length > 0 && (
                <div className="rounded-xl border border-border bg-surface-1 p-4">
                  <h3 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
                    <Trophy size={14} className="text-amber-400" />
                    Top-5 Predictions
                  </h3>
                  <div className="space-y-2">
                    {result.top_5_predictions.map((item, i) => (
                      <div key={i} className="flex items-center gap-3">
                        <span className={`shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${i === 0 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-surface-2 text-foreground/50'}`}>
                          {item.rank}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between mb-0.5">
                            <span className={`text-xs font-medium truncate ${i === 0 ? 'text-emerald-300' : 'text-foreground/80'}`}>{item.label}</span>
                            <span className="text-xs font-semibold tabular-nums text-foreground/70 ml-2">{item.confidence.toFixed(1)}%</span>
                          </div>
                          <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${i === 0 ? 'bg-emerald-500' : 'bg-foreground/20'}`}
                              style={{ width: `${Math.min(item.confidence, 100)}%` }}
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Raw JSON toggle */}
              <div className="rounded-xl border border-border bg-surface-1 overflow-hidden">
                <button
                  id="botaniq-raw-toggle"
                  onClick={() => setShowRaw((v) => !v)}
                  className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-surface-2 transition-colors"
                >
                  <span className="flex items-center gap-1.5 text-foreground/70">
                    <Settings2 size={13} />Raw JSON Response
                  </span>
                  {showRaw ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
                {showRaw && (
                  <pre className="p-4 text-[11px] leading-relaxed text-foreground/70 bg-surface-2 overflow-x-auto max-h-64 border-t border-border">
                    {JSON.stringify(result.raw, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          )}

          {/* Empty state */}
          {phase === 'idle' && !result && (
            <div className="rounded-xl border border-dashed border-border bg-surface-1 flex flex-col items-center justify-center text-center p-10 min-h-[240px]">
              <Leaf size={36} className="text-foreground/20 mb-3" />
              <p className="text-sm font-medium text-foreground/50">Select an image to get started</p>
              <p className="text-xs text-foreground/35 mt-1">Upload, paste a URL, or pick from the test dataset</p>
            </div>
          )}
        </motion.div>
      </div>

      {/* History table */}
      {history.length > 0 && (
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.15, ease: 'easeOut' }}
          className="rounded-xl border border-border bg-surface-1 overflow-hidden"
        >
          <div className="px-4 py-3 border-b border-border flex items-center gap-2">
            <History size={14} className="text-foreground/50" />
            <h2 className="text-sm font-semibold">Test History</h2>
            <span className="ml-auto text-xs text-foreground/45">{history.length} recent run{history.length !== 1 ? 's' : ''}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs" aria-label="BotaniQ inference history">
              <thead>
                <tr className="border-b border-border bg-surface-2 text-foreground/50">
                  <th className="text-left px-4 py-2 font-medium">Image</th>
                  <th className="text-left px-4 py-2 font-medium">Prediction</th>
                  <th className="text-left px-4 py-2 font-medium">Type</th>
                  <th className="text-left px-4 py-2 font-medium">Confidence</th>
                  <th className="text-left px-4 py-2 font-medium">Time</th>
                  <th className="text-left px-4 py-2 font-medium">Source</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                  <th className="text-left px-4 py-2 font-medium">Run at</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id} className="border-b border-border/50 hover:bg-surface-2/50 transition-colors">
                    <td className="px-4 py-2.5 font-mono text-foreground/60 max-w-[130px] truncate">{row.image_filename}</td>
                    <td className="px-4 py-2.5 font-medium text-foreground/90">{row.prediction ?? '—'}</td>
                    <td className="px-4 py-2.5 text-foreground/60">{row.plant_type ?? '—'}</td>
                    <td className="px-4 py-2.5 tabular-nums text-emerald-400 font-semibold">
                      {row.confidence != null ? `${row.confidence.toFixed(1)}%` : '—'}
                    </td>
                    <td className="px-4 py-2.5 tabular-nums text-foreground/60">
                      {row.inference_time_ms != null ? `${row.inference_time_ms}ms` : '—'}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="px-1.5 py-0.5 rounded bg-surface-2 border border-border text-[10px] font-medium capitalize">{row.source}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${row.status === 'completed' ? 'bg-success/10 text-success border border-success/30' : 'bg-red-500/10 text-red-400 border border-red-500/30'}`}>
                        {row.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-foreground/45">
                      {row.created_at ? new Date(row.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </motion.div>
      )}
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ImagePreviewCard({ selected, onClear }: { selected: SelectedImage; onClear: () => void }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-emerald-500/30 bg-emerald-500/5 text-sm">
      <ImageIcon size={13} className="shrink-0 text-emerald-400" />
      <span className="flex-1 min-w-0 truncate text-foreground/80 text-xs">{selected.filename}</span>
      {selected.sizeBytes && <span className="text-[11px] text-foreground/45 shrink-0">{fmtBytes(selected.sizeBytes)}</span>}
      <button
        id="botaniq-clear-image"
        onClick={(e) => { e.stopPropagation(); onClear(); }}
        className="shrink-0 text-foreground/40 hover:text-foreground transition-colors"
        aria-label="Clear selected image"
      >
        <X size={13} />
      </button>
    </div>
  );
}

function MetricChip({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-surface-2 border border-border text-xs">
      <span className="text-foreground/50">{icon}</span>
      <span className="text-foreground/50">{label}:</span>
      <span className="font-medium text-foreground/80">{value}</span>
    </div>
  );
}

function ConfigCard({ config, loading }: { config: BotaniQConfig | null; loading: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-border bg-surface-1 overflow-hidden">
      <button
        id="botaniq-config-toggle"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-surface-2 transition-colors"
      >
        <span className="flex items-center gap-1.5 text-foreground/70">
          <Settings2 size={13} />Model Configuration
        </span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && (
        <div className="border-t border-border divide-y divide-border/50 text-xs">
          {loading ? (
            <div className="px-4 py-3 text-foreground/50 flex items-center gap-2"><Loader2 size={12} className="animate-spin" />Loading…</div>
          ) : config ? (
            [
              ['Model', config.model],
              ['Version', config.model_version],
              ['Input', config.input_resolution],
              ['Provider', config.provider],
              ['Compute', config.compute],
              ['Max upload', `${config.max_upload_mb} MB`],
              ['Formats', config.allowed_extensions.join(', ')],
              ['Classes', config.classes_available != null ? String(config.classes_available) : 'N/A'],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between px-4 py-2">
                <span className="text-foreground/50">{k}</span>
                <span className="font-medium text-foreground/80 text-right max-w-[60%] truncate">{v}</span>
              </div>
            ))
          ) : (
            <div className="px-4 py-3 text-foreground/50">Config unavailable</div>
          )}
        </div>
      )}
    </div>
  );
}
