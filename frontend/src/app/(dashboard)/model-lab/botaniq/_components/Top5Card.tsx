'use client';

import { BarChart3 } from 'lucide-react';
import type { BotaniQInferenceResult } from '@/lib/api';

interface Top5CardProps {
  result: BotaniQInferenceResult;
}

export function Top5Card({ result }: Top5CardProps) {
  return (
    <div className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 h-full min-h-[260px] flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 flex items-center justify-center shrink-0">
          <BarChart3 size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-lg tracking-tight leading-tight text-foreground">Top-5 Predictions</h3>
          <p className="text-xs text-foreground/80 leading-relaxed mt-0.5">Ranked by confidence</p>
        </div>
      </div>
      {result.top_5_predictions && result.top_5_predictions.length > 0 ? (
        <div className="flex-1 space-y-2">
          {result.top_5_predictions.slice(0, 5).map((item, i) => (
            <div key={i} className="flex items-center gap-3">
              <span
                className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${
                  i === 0 ? 'bg-emerald-500/20 text-emerald-800 dark:text-emerald-300' : 'bg-surface-2 text-foreground/80'
                }`}
              >
                {item.rank}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-0.5">
                  <span className={`text-sm font-medium truncate ${i === 0 ? 'text-emerald-800 dark:text-emerald-300' : 'text-foreground'}`}>
                    {item.label}
                  </span>
                  <span className="text-sm font-semibold tabular-nums text-foreground/90 ml-2">
                    {item.confidence.toFixed(1)}%
                  </span>
                </div>
                <div className="h-2 rounded-full bg-surface-2 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${i === 0 ? 'bg-emerald-500' : 'bg-foreground/40'}`}
                    style={{ width: `${Math.min(item.confidence, 100)}%` }}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-foreground/60 text-sm">
          No predictions available
        </div>
      )}
    </div>
  );
}