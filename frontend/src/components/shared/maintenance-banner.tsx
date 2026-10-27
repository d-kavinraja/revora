'use client';

import { useQuery } from '@tanstack/react-query';
import { Wrench } from 'lucide-react';

import { api } from '@/lib/api';
import { useThemeStore } from '@/store/useThemeStore';

/**
 * Maintenance banner (§12.4 fallback, C5).
 *
 * Already-open tabs and page loads that raced the edge redirect surface the
 * same message the /maintenance page shows. Polls `/platform/status` every
 * 5s (matching the backend TTL cache) and renders nothing while off.
 */
export function MaintenanceBanner({ className }: { className?: string }) {
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

  const { data } = useQuery({
    queryKey: ['platform-status'],
    queryFn: api.getPlatformStatus,
    refetchInterval: 5_000,
    staleTime: 5_000,
    retry: false,
  });

  const maintenance = data?.maintenance;
  if (!maintenance?.enabled) return null;

  const eta = maintenance.expected_return_at
    ? new Date(maintenance.expected_return_at)
    : null;
  const etaLabel =
    eta && !Number.isNaN(eta.getTime()) ? eta.toLocaleString() : null;

  return (
    <div
      role="status"
      className={`flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b px-4 py-2 text-center text-xs md:text-sm ${
        isLight
          ? 'border-amber-300 bg-amber-100 text-amber-900'
          : 'border-amber-800/60 bg-amber-950/40 text-amber-200'
      } ${className ?? ''}`}
    >
      <span className="inline-flex items-center gap-1.5 font-semibold">
        <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
        {maintenance.title ?? 'Maintenance in progress'}
      </span>
      {maintenance.message && <span>{maintenance.message}</span>}
      {etaLabel && (
        <span className="font-mono text-[11px] opacity-80">
          Expected back: {etaLabel}
        </span>
      )}
    </div>
  );
}
