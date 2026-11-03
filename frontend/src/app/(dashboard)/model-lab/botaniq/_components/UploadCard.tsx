'use client';

import { useRef, useState, useEffect, type KeyboardEvent } from 'react';
import { ChevronDown, ChevronUp, CloudUpload, Database, ImageIcon, Leaf, Link2, Loader2, Search, Settings, Upload, XCircle } from 'lucide-react';
import type { BotaniQConfig } from '@/lib/api';
import type { BotaniQSampleImage } from '@/lib/api';
import type { InputTab, SelectedImage } from './types';
import { fmtBytes } from './types';
import { botaniqApi } from '@/lib/api';

interface UploadCardProps {
  config: BotaniQConfig | null;
  tab: InputTab;
  onTabChange: (t: InputTab) => void;
  onFile: (f: File | null) => void;
  urlInput: string;
  onUrlChange: (v: string) => void;
  onCommitUrl: () => void;
  selected: SelectedImage | null;
  onClear: () => void;
  onRun: () => void;
  canRun: boolean;
  busy: boolean;
  onSelectDataset: (img: BotaniQSampleImage) => void;
}

export function UploadCard(props: UploadCardProps) {
  const {
    config,
    tab,
    onTabChange,
    onFile,
    urlInput,
    onUrlChange,
    onCommitUrl,
    selected,
  onClear,
  onRun,
  canRun,
  busy,
  onSelectDataset,
} = props;
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [showModelConfig, setShowModelConfig] = useState(false);
  const maxMb = config?.max_upload_mb ?? 20;
  const formats = (config?.allowed_extensions ?? ['.jpg', '.jpeg', '.png', '.webp', '.avif', '.gif']).join(' / ').toUpperCase();
  const ownSelection = selected && (selected.kind === 'upload' || selected.kind === 'url') ? selected : null;
  const tabs: { id: InputTab; label: string; icon: React.ReactNode }[] = [
    { id: 'upload', label: 'Upload', icon: <Upload size={13} /> },
    { id: 'url', label: 'URL', icon: <Link2 size={13} /> },
    { id: 'dataset', label: 'Dataset', icon: <Database size={13} /> },
  ];
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const onTabKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number | null = null;
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    e.preventDefault();
    tabRefs.current[next]?.focus();
    onTabChange(tabs[next].id);
  };

  return (
    <section
      aria-label="Upload test image"
      className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 flex flex-col h-full min-w-0 transition-colors hover:border-emerald-500/40 focus-within:border-emerald-500/50"
    >
      <div className="flex items-center gap-2">
        <span className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 flex items-center justify-center shrink-0">
          <Upload size={20} />
        </span>
        <div className="min-w-0">
          <h2 className="font-semibold text-lg sm:text-xl tracking-tight leading-tight text-foreground">Image Input</h2>
          <p className="text-sm text-foreground/80 leading-relaxed mt-0.5">
            Upload an image, paste a URL, or select from the test dataset.
          </p>
        </div>
      </div>

      <div className="flex gap-1 mt-3 p-1 rounded-lg bg-surface-2 border border-border" role="tablist" aria-label="Input source">
        {tabs.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[i] = el;
            }}
            role="tab"
            id={`botaniq-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="botaniq-upload-panel"
            tabIndex={tab === t.id ? 0 : -1}
            onKeyDown={(e) => onTabKeyDown(e, i)}
            onClick={() => onTabChange(t.id)}
            className={`flex-1 px-3 min-h-[40px] inline-flex items-center justify-center gap-1.5 rounded-md text-xs font-medium transition-colors ${
              tab === t.id
                ? 'bg-surface-1 text-foreground shadow-sm border border-border'
                : 'text-foreground/80 hover:text-foreground'
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      <div
        className="mt-3 flex flex-col flex-1 min-h-0"
        role="tabpanel"
        id="botaniq-upload-panel"
        aria-labelledby={tab === 'upload' ? 'botaniq-tab-upload' : tab === 'url' ? 'botaniq-tab-url' : 'botaniq-tab-dataset'}
      >
        {tab === 'upload' ? (
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
                onFile(e.dataTransfer.files?.[0] ?? null);
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
              aria-label="Drag and drop an image file here, or click to browse"
              className={`flex-1 flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-4 sm:p-6 text-center transition-all cursor-pointer min-h-[180px] ${
                dragOver
                  ? 'border-emerald-500 bg-emerald-500/5 scale-[1.01]'
                  : 'border-border bg-surface-2 hover:border-emerald-500/40'
              }`}
            >
              <CloudUpload
                size={30}
                className="mx-auto text-emerald-800 dark:text-emerald-300 mb-1.5"
                aria-hidden="true"
              />
              <p className="text-sm font-semibold tracking-tight text-foreground">Drag and drop an image here</p>
              <p className="text-xs text-foreground/80 mt-0.5">or click to browse</p>
              <input
                ref={fileRef}
                type="file"
                accept=".jpg,.jpeg,.png,.webp,.avif,.gif,image/*"
                className="hidden"
                aria-label="Choose image file"
                onChange={(e) => onFile(e.target.files?.[0] ?? null)}
              />
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  fileRef.current?.click();
                }}
                className="mt-2.5 px-4 min-h-[40px] inline-flex items-center justify-center rounded-lg text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-500 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50"
              >
                Choose Image
              </button>
            </div>
            <p className="text-xs text-foreground/80 mt-2 text-center">
              Supported formats: {formats} · Max size: {maxMb} MB
            </p>
          </>
        ) : tab === 'url' ? (
          <div className="space-y-3">
            <label htmlFor="botaniq-url-input" className="block text-xs font-medium text-foreground/90 mb-1">
              Public image URL
            </label>
            <div className="flex gap-2">
              <input
                id="botaniq-url-input"
                type="url"
                value={urlInput}
                onChange={(e) => onUrlChange(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && onCommitUrl()}
                placeholder="https://example.com/herb.jpg"
                className="flex-1 text-sm px-3 py-2 rounded-lg border border-border bg-surface-2 text-foreground placeholder:text-foreground/60 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50"
              />
              <button
                id="botaniq-url-confirm"
                onClick={onCommitUrl}
                disabled={!urlInput.trim()}
                className="px-3 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50"
              >
                Set
              </button>
            </div>
            <p className="text-[11px] text-foreground/80 leading-relaxed">
              The backend fetches the URL server-side. Only publicly accessible images are supported.
            </p>
          </div>
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto">
            <DatasetTabContent
              selected={selected}
              onSelectDataset={onSelectDataset}
            />
          </div>
        )}

        {ownSelection && (
          <div className="mt-2.5 rounded-lg bg-surface-2 p-2.5 text-xs border border-border">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium truncate flex items-center gap-1.5 text-foreground">
                <ImageIcon size={13} className="shrink-0 text-emerald-800 dark:text-emerald-300" />
                {ownSelection.filename}
              </p>
              <button
                onClick={onClear}
                className="shrink-0 text-foreground/80 hover:text-foreground transition-colors"
                aria-label="Remove selected image"
              >
                <XCircle size={15} />
              </button>
            </div>
            <p className="text-foreground/80 mt-0.5">
              {fmtBytes(ownSelection.sizeBytes)}
            </p>
          </div>
        )}

        <div className="mt-4 space-y-3">
          <button
            onClick={onRun}
            disabled={!canRun || busy}
            className="w-full sm:w-auto inline-flex items-center justify-center gap-1.5 px-6 py-3 rounded-lg text-sm font-semibold bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50"
          >
            {busy ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Leaf size={16} />
            )}
            {busy ? 'Identifying…' : 'Identify Plant'}
          </button>

          <ModelConfigCollapsible
            config={config}
            isOpen={showModelConfig}
            onToggle={() => setShowModelConfig(!showModelConfig)}
          />
        </div>
      </div>
    </section>
  );
}

function DatasetTabContent({
  selected,
  onSelectDataset,
}: {
  selected: SelectedImage | null;
  onSelectDataset: (img: BotaniQSampleImage) => void;
}) {
  const [filter, setFilter] = useState('');
  const [dataset, setDataset] = useState<BotaniQSampleImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectingId, setSelectingId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    botaniqApi.getDataset().then((d) => {
      if (alive) {
        setDataset(d);
        setLoading(false);
      }
    }).catch((e) => {
      if (alive) {
        setError(e?.message || 'Failed to load dataset');
        setLoading(false);
      }
    });
    return () => { alive = false; };
  }, []);

  const filtered = dataset.filter((img) =>
    filter === '' ||
    img.filename.toLowerCase().includes(filter.toLowerCase()) ||
    (img.plant_name && img.plant_name.toLowerCase().includes(filter.toLowerCase())),
  );

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <Database size={32} className="text-red-500/60 mb-2" />
        <p className="text-sm font-medium text-red-600 dark:text-red-400">Failed to load dataset</p>
        <p className="text-xs text-foreground/60 mt-1">{error}</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 gap-2 text-foreground/80 text-sm">
        <Database size={16} className="animate-pulse" /> Loading dataset…
      </div>
    );
  }

  if (dataset.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <Database size={32} className="text-foreground/30 mb-2" />
        <p className="text-sm font-medium text-foreground/80">No test images yet</p>
        <p className="text-xs text-foreground/60 mt-1">Drop images into backend/app/botaniq/dataset/</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
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
      <div className="space-y-2 max-h-[300px] overflow-y-auto pr-0.5">
        {filtered.map((img) => {
          const active = selected?.testImageId === img.id;
          const selecting = selectingId === img.id;
          return (
            <button
              key={img.id}
              type="button"
              disabled={selecting}
              onClick={async () => {
                setSelectingId(img.id);
                try {
                  await onSelectDataset(img);
                } finally {
                  setSelectingId(null);
                }
              }}
              className={`w-full text-left px-3 py-2 rounded-lg border transition-all text-sm ${
                active
                  ? 'border-emerald-500/70 bg-emerald-500/10'
                  : 'border-border bg-surface-2 hover:border-emerald-500/40'
              } ${selecting ? 'opacity-60 cursor-wait' : ''}`}
            >
              <div className="flex items-center gap-2">
                {selecting && (
                  <span className="w-3 h-3 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <span className="font-medium block truncate">{img.plant_name ?? img.filename}</span>
                  <span className="text-[11px] text-foreground/75 flex items-center gap-2 mt-0.5">
                    {img.plant_type ? <span>{img.plant_type}</span> : null}
                    {img.size_bytes ? <span>{fmtBytes(img.size_bytes)}</span> : null}
                  </span>
                </div>
              </div>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <p className="text-xs text-foreground/80 text-center py-4">No matches</p>
        )}
      </div>
    </div>
  );
}

function ModelConfigCollapsible({
  config,
  isOpen,
  onToggle,
}: {
  config: BotaniQConfig | null;
  isOpen: boolean;
  onToggle: () => void;
}) {
  if (!config) return null;

  return (
    <div className="rounded-lg border border-border bg-surface-2 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-foreground/80 hover:text-foreground transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <Settings size={13} /> Model Configuration
        </span>
        {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {isOpen && (
        <div className="px-3 pb-3 pt-2 border-t border-border space-y-2 text-xs">
          <div className="flex justify-between"><span className="text-foreground/70">Model</span><span className="font-medium text-foreground truncate max-w-[200px]">{config.model}</span></div>
          {config.model_version && <div className="flex justify-between"><span className="text-foreground/70">Version</span><span className="font-medium text-foreground">{config.model_version}</span></div>}
          <div className="flex justify-between"><span className="text-foreground/70">Input Resolution</span><span className="font-medium text-foreground">{config.input_resolution}</span></div>
          <div className="flex justify-between"><span className="text-foreground/70">Provider</span><span className="font-medium text-foreground">{config.provider}</span></div>
          <div className="flex justify-between"><span className="text-foreground/70">Compute</span><span className="font-medium text-foreground">{config.compute}</span></div>
          <div className="flex justify-between"><span className="text-foreground/70">Classes</span><span className="font-medium text-foreground">{config.classes_available ?? 'N/A'}</span></div>
          <div className="flex justify-between"><span className="text-foreground/70">Max Upload</span><span className="font-medium text-foreground">{config.max_upload_mb} MB</span></div>
        </div>
      )}
    </div>
  );
}