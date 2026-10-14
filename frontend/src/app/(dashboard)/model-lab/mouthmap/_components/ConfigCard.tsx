'use client';

import { Cpu } from 'lucide-react';
import type { MouthMapConfig } from '@/lib/api';

interface ConfigCardProps {
  config: MouthMapConfig | null;
  health: string;
}

export function ConfigCard({ config, health }: ConfigCardProps) {
  const rows: [string, string][] = [
    ['Model', config?.model ?? 'MouthMap'],
    ['Version', config?.model_version ?? 'N/A'],
    ['Input', `${config?.input_frames ?? 75} frames · ${config?.input_resolution ?? '46x140 grayscale'}`],
    ['Provider', config?.provider ?? 'Hugging Face'],
    ['Compute', config?.compute ?? 'Hosted Inference'],
    ['Upload limit', `${config?.max_upload_mb ?? 50} MB`],
  ];
  return (
  <section
    aria-label="Model configuration"
    className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 flex flex-col h-full transition-colors hover:border-ai-purple/30"
  >
    <div className="flex items-center gap-2">
      <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
        <Cpu size={20} />
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="font-semibold text-xl tracking-tight leading-tight">Model Configuration</h2>
        <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
          Live model settings for testing.
        </p>
      </div>
        <span className="shrink-0 inline-flex items-center gap-1.5 text-xs text-foreground/70">
          <span
            className={`w-2 h-2 rounded-full ${health === 'available' ? 'bg-success' : health === 'unavailable' ? 'bg-error' : 'bg-warning animate-pulse'}`}
            aria-hidden="true"
          />
          {health === 'available'
            ? 'Available'
            : health === 'unavailable'
              ? 'Unavailable'
              : 'Checking...'}
        </span>
      </div>
      <dl className="mt-4 space-y-2 flex-1">
        {rows.map(([k, v]) => (
          <div
            key={k}
            className="flex items-center justify-between gap-3 rounded-lg bg-surface-2 px-3 py-2"
          >
            <dt className="text-xs text-foreground/65 shrink-0">{k}</dt>
            <dd className="text-sm font-medium text-right truncate tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
