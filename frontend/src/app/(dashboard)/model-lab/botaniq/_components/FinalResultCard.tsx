'use client';

import { Settings2, Trophy } from 'lucide-react';
import type { BotaniQInferenceResult } from '@/lib/api';

interface FinalResultCardProps {
  result: BotaniQInferenceResult;
}

function MetricChip({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-surface-2 border border-border text-xs">
      <span className="text-foreground/70">{icon}</span>
      <span className="text-foreground/70">{label}:</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  );
}

export function FinalResultCard({ result }: FinalResultCardProps) {
  const greenText = 'text-emerald-800 dark:text-emerald-300';
  return (
    <div className="rounded-xl border border-emerald-500/40 bg-gradient-to-br from-emerald-50/60 via-surface-1 to-surface-1 dark:from-emerald-950/30 dark:via-surface-1 dark:to-surface-1 p-4 md:p-5 h-full min-h-[260px] flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 flex items-center justify-center shrink-0">
          <Trophy size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-lg tracking-tight leading-tight text-foreground">Final Result</h3>
          <p className="text-xs text-foreground/80 leading-relaxed mt-0.5">Top prediction</p>
        </div>
      </div>
      <div className="flex-1 flex flex-col justify-center">
        <p className="text-xs font-medium text-foreground/70 uppercase tracking-widest mb-1">Identified as</p>
        <h2 className={`text-2xl md:text-3xl font-bold tracking-tight leading-tight ${greenText} mb-2`}>
          {result.prediction}
        </h2>
        {result.plant_name && result.plant_type && (
          <p className="text-sm text-foreground/75 mb-2">
            <span className="font-medium text-foreground">{result.plant_name}</span>
            {' · '}
            <span className="px-1.5 py-0.5 rounded bg-surface-2 text-[11px] font-medium text-foreground/90">{result.plant_type}</span>
          </p>
        )}
        <div className="text-center mt-2">
          <div className={`text-4xl font-black tabular-nums leading-none ${greenText}`}>
            {result.confidence != null ? `${result.confidence.toFixed(1)}%` : 'N/A'}
          </div>
          <p className="text-xs text-foreground/70 mt-1">Confidence</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-3 mt-4 pt-4 border-t border-border/70">
        <MetricChip icon={<Settings2 size={12} />} label="Inference" value={result.inference_time_ms != null ? `${result.inference_time_ms}ms` : 'N/A'} />
        <MetricChip icon={<Settings2 size={12} />} label="Model" value={result.model} />
        <MetricChip icon={<Settings2 size={12} />} label="Classes" value={result.classes_available != null ? String(result.classes_available) : 'N/A'} />
        {result.model_version && <MetricChip icon={<Settings2 size={12} />} label="Version" value={result.model_version} />}
      </div>
    </div>
  );
}
