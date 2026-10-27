'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Wrench } from 'lucide-react';

import { api } from '@/lib/api';
import { useThemeStore } from '@/store/useThemeStore';
import { Footer } from '@/components/ui/footer';

const POLL_INTERVAL_MS = 10_000;

/**
 * Public maintenance page (§12.4).
 *
 * Standalone (no dashboard shell), theme-aware and accessible. Shows the
 * admin-authored title/message/expected-return only — never internal
 * reasons, stack traces or URLs. Polls `/platform/status` and returns the
 * visitor to the app automatically once the switch flips off.
 */
export default function MaintenancePage() {
  const router = useRouter();
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

  const { data } = useQuery({
    queryKey: ['platform-status'],
    queryFn: api.getPlatformStatus,
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 5_000,
    retry: false,
  });

  const maintenance = data?.maintenance;

  useEffect(() => {
    if (data && maintenance?.enabled === false) {
      router.replace('/');
    }
  }, [data, maintenance?.enabled, router]);

  const eta = maintenance?.expected_return_at
    ? new Date(maintenance.expected_return_at)
    : null;
  const etaLabel =
    eta && !Number.isNaN(eta.getTime()) ? eta.toLocaleString() : null;

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <div className="flex flex-1 items-center justify-center px-4 py-16">
        <div
          role="status"
          aria-live="polite"
          className={`w-full max-w-lg rounded-3xl border p-8 text-center backdrop-blur-md ${
            isLight
              ? 'border-border bg-surface-1/80 shadow-slate-200/50'
              : 'border-zinc-800 bg-zinc-950/80 shadow-black/30'
          } shadow-xl`}
        >
          <div
            className={`mx-auto flex h-16 w-16 items-center justify-center rounded-2xl ${
              isLight ? 'bg-amber-100 text-amber-600' : 'bg-amber-950/50 text-amber-300'
            }`}
          >
            <Wrench className="h-7 w-7" aria-hidden="true" />
          </div>

          <h1 className="mt-6 text-2xl font-bold tracking-tight md:text-3xl">
            {maintenance?.title ?? 'Under maintenance'}
          </h1>

          <p
            className={`mt-3 text-sm leading-relaxed ${
              isLight ? 'text-muted-foreground' : 'text-zinc-400'
            }`}
          >
            {maintenance?.message ??
              'Revora is receiving an upgrade. We will be back shortly — no action is needed on your side.'}
          </p>

          {etaLabel && (
            <p className="mt-4 font-mono text-xs opacity-80">
              Expected back: {etaLabel}
            </p>
          )}

          <p className="mt-8 font-mono text-[11px] uppercase tracking-widest opacity-60">
            This page refreshes automatically
          </p>
        </div>
      </div>

      <Footer
        logoSrc="/revora-logo.png"
        className="relative z-20 border-t border-border bg-background/95 shadow-[0_-8px_30px_rgba(0,0,0,0.12)] backdrop-blur-xl"
      />
    </div>
  );
}
