'use client';

import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { BrainIcon } from '@animateicons/react/lucide';
import { motion, useReducedMotion } from 'motion/react';
import type { MouthMapInferenceResult } from '@/lib/api';

interface InferenceResultCardProps {
  result: MouthMapInferenceResult;
}

export function InferenceResultCard({ result }: InferenceResultCardProps) {
  const reduce = useReducedMotion();

  return (
    <div className="rounded-xl border border-border bg-surface-1 p-4 transition-colors hover:border-ai-purple/30 flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
          <BrainIcon size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-xl leading-tight">Inference Result</h3>
          <p className="text-sm text-foreground/70 leading-relaxed mt-0.5">
            Model prediction and ground-truth comparison
          </p>
        </div>
      </div>

      <motion.div
        key={result.prediction}
        initial={reduce ? false : { opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex-1 flex flex-col justify-center space-y-3"
      >
        <div className="rounded-lg bg-surface-2 px-3 py-2.5">
          <p className="text-xs text-foreground/65">Prediction</p>
          <p className="font-semibold mt-0.5 break-words text-ai-purple text-lg leading-snug tabular-nums">
            {result.prediction || '—'}
          </p>
        </div>

        <div className="rounded-lg bg-surface-2 px-3 py-2.5">
          <p className="text-xs text-foreground/65">Ground Truth</p>
          {result.expected ? (
            <p className="font-medium mt-0.5 break-words text-sm leading-snug">
              {result.expected}
            </p>
          ) : (
            <p className="text-sm text-foreground/70 mt-0.5">Not available</p>
          )}
        </div>

        <div className="rounded-lg bg-surface-2 px-3 py-2.5">
          <p className="text-xs text-foreground/65">Result</p>
          {result.expected ? (
            result.is_match ? (
              <p className="mt-1 inline-flex items-center gap-1.5 text-sm font-semibold text-success">
                <CheckCircle2 size={15} /> Match
              </p>
            ) : (
              <p className="mt-1 inline-flex items-center gap-1.5 text-sm font-semibold text-warning">
                <AlertTriangle size={15} /> Mismatch
              </p>
            )
          ) : (
            <p className="text-sm text-foreground/70 mt-0.5">
              No ground truth for this video
            </p>
          )}
        </div>
      </motion.div>
    </div>
  );
}
