'use client';

import { useRef, useState, type KeyboardEvent } from 'react';
import { Film, Palette, Ruler, ScanEye, Scissors } from 'lucide-react';
import { MODEL_INPUT } from './types';
import { MouthRegionViz, type VizMode } from './MouthRegionViz';

interface ModelInputRegionCardProps {
  objectUrl: string;
  frameSize: { w: number; h: number } | null;
}

const DETAILS: { icon: typeof Ruler; label: string; value: string }[] = [
  { icon: Ruler, label: 'Input Resolution', value: `${MODEL_INPUT.h}×${MODEL_INPUT.w}` },
  { icon: Film, label: 'Frames', value: String(MODEL_INPUT.frames) },
  { icon: Palette, label: 'Channels', value: 'Grayscale' },
  { icon: Scissors, label: 'Source', value: 'Fixed Crop' },
];

export function ModelInputRegionCard({ objectUrl, frameSize }: ModelInputRegionCardProps) {
  const [mode, setMode] = useState<VizMode>('crop');
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const onTabKeyDown = (
    e: KeyboardEvent<HTMLButtonElement>,
    index: number,
    tabs: { id: VizMode; label: string }[],
  ) => {
    let next: number | null = null;
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    e.preventDefault();
    tabRefs.current[next]?.focus();
    setMode(tabs[next].id);
  };

  return (
    <div className="rounded-xl border border-border bg-surface-1 p-4 transition-colors hover:border-ai-purple/30 flex flex-col min-w-0">
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 mb-3">
        <div className="flex items-center gap-2 min-w-0 sm:flex-1">
          <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
            <ScanEye size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold text-xl leading-tight">Model Input Region</h3>
            <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
              MouthMap preprocessing — what the model actually sees
            </p>
          </div>
        </div>
        <div
          className="flex gap-1 p-0.5 rounded-lg bg-surface-2 border border-border w-full sm:w-auto min-w-0"
          role="tablist"
          aria-label="Visualization mode"
        >
          {(
            [
              { id: 'crop', label: 'Mouth Crop' },
              { id: 'full', label: 'Original Frame' },
            ] as { id: VizMode; label: string }[]
          ).map((t, i, arr) => (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[i] = el;
              }}
              role="tab"
              id={`ml-viz-tab-${t.id}`}
              aria-selected={mode === t.id}
              aria-controls="ml-viz-panel"
              tabIndex={mode === t.id ? 0 : -1}
              onKeyDown={(e) => onTabKeyDown(e, i, arr)}
              onClick={() => setMode(t.id)}
              className={`flex-1 justify-center whitespace-nowrap px-3 min-h-[40px] inline-flex items-center rounded-md text-xs font-medium transition-colors ${
                mode === t.id
                  ? 'bg-surface-1 text-foreground shadow-sm border border-border'
                  : 'text-foreground/60 hover:text-foreground'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Fixed-crop facts — explicitly not a landmark detector. */}
      <div className="rounded-lg border border-brand/30 bg-brand/5 px-3 py-1.5 mb-2">
        <p className="text-xs font-semibold text-ai-purple leading-tight">
          Fixed Preprocessing Crop
        </p>
        <p className="text-xs text-foreground/65 leading-relaxed mt-0.5">
          x={MODEL_INPUT.x} · y={MODEL_INPUT.y} · width={MODEL_INPUT.w} · height=
          {MODEL_INPUT.h} · {MODEL_INPUT.frames} frames · grayscale — not detected landmarks.
        </p>
      </div>

      <div
        role="tabpanel"
        id="ml-viz-panel"
        aria-labelledby={mode === 'crop' ? 'ml-viz-tab-crop' : 'ml-viz-tab-full'}
      >
        <MouthRegionViz objectUrl={objectUrl} frameSize={frameSize} mode={mode} />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2">
        {DETAILS.map((d) => (
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
    </div>
  );
}
