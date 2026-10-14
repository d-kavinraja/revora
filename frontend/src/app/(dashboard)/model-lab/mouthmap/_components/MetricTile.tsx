'use client';

import type { LucideIcon } from 'lucide-react';

interface MetricTileProps {
  icon: LucideIcon;
  label: string;
  value: string;
}

export function MetricTile({ icon: Icon, label, value }: MetricTileProps) {
  return (
    <div className="rounded-lg bg-surface-2 p-3 min-w-0 flex flex-col justify-center">
      <p className="flex items-center gap-1.5 text-xs text-foreground/65 leading-tight">
        <Icon size={16} className="text-brand shrink-0" aria-hidden="true" />
        <span className="truncate">{label}</span>
      </p>
      <p className="font-semibold text-base mt-1 truncate tabular-nums" title={value}>
        {value}
      </p>
    </div>
  );
}
