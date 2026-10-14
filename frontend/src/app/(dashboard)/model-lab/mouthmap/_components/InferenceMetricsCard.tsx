'use client';

import { Clock, Cpu, Gauge, Layers } from 'lucide-react';
import type { MouthMapInferenceResult } from '@/lib/api';
import { MetricTile } from './MetricTile';
import { metric } from './types';

interface InferenceMetricsCardProps {
  result: MouthMapInferenceResult;
}

export function InferenceMetricsCard({ result }: InferenceMetricsCardProps) {
  return (
    <div className="rounded-xl border border-border bg-surface-1 p-4 transition-colors hover:border-ai-purple/30 flex flex-col min-w-0">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
          <Gauge size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-xl leading-tight">Inference Metrics</h3>
          <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
            Key metrics from the inference run
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 flex-1 content-center">
        <MetricTile icon={Gauge} label="Confidence" value={metric(result.confidence)} />
        <MetricTile
          icon={Clock}
          label="Inference Time"
          value={result.inference_time_ms != null ? `${result.inference_time_ms} ms` : 'N/A'}
        />
        <MetricTile
          icon={Layers}
          label="Frames Processed"
          value={metric(result.frames_processed)}
        />
        <MetricTile icon={Cpu} label="Model" value={result.model || 'MouthMap'} />
      </div>
    </div>
  );
}
