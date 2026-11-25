'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Image from 'next/image';
import { RefreshCwIcon, TriangleAlertIcon } from 'lucide-react';
import { api, KllmActivityItem, KllmStatus, KllmTelemetry } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { ModelIcon } from '@/components/ui/model-icon';
import { Pill, type PillTone } from '@/components/shared/pill';
import { KLLM_MANAGEMENT_LABEL, KLLM_PROVIDER, modelDisplayName } from '@/lib/chat-state';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { timeAgo } from '@/components/shared/time-ago';
import { useBrowserSessionId } from '@/hooks/use-kllm-session-presence';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';
import { PageHeader } from '@/components/shared/page-header';
import { SettingsShell } from '@/components/shared/settings-shell';

const STATUS_INTERVAL_MS = 15_000;
const TELEMETRY_INTERVAL_MS = 5_000;
const MAX_BACKOFF_MS = 60_000;

const BACKEND_TONE: Record<string, PillTone> = {
  running: 'success',
  draining: 'warning',
  retiring: 'warning',
  unhealthy: 'error',
};

const READINESS_TONE: Record<string, PillTone> = {
  ready: 'success',
  loading: 'warning',
  unloaded: 'muted',
  failed: 'error',
  unavailable: 'error',
  stale: 'warning',
};

const READINESS_LABEL: Record<string, string> = {
  ready: 'Ready',
  loading: 'Loading',
  unloaded: 'Not loaded',
  failed: 'Failed',
  unavailable: 'Unavailable',
  stale: 'Stale',
};

const READINESS_RANK: Record<string, number> = {
  ready: 0,
  loading: 1,
};

function readinessRank(value: string | undefined): number {
  return READINESS_RANK[(value ?? '').toLowerCase()] ?? 2;
}

function errorMessage(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const response = (err as { response?: { data?: { detail?: unknown } } })
      .response;
    const detail = response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (typeof (err as Error).message === 'string') {
      return (err as Error).message;
    }
  }
  return 'Something went wrong. Please try again.';
}

function formatDuration(total: number | null | undefined): string {
  if (total == null || !Number.isFinite(total)) return '—';
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${total}s`;
}

function formatMib(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value >= 1024) return `${(value / 1024).toFixed(1)} GB`;
  return `${Math.round(value)} MB`;
}

function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toFixed(digits);
}

/**
 * Read-only kLLM status for ordinary users.
 *
 * Lifecycle control (load/unload, backend stop/rotate/pin, always-on pool and
 * automatic-loading policy) is administrator-only and lives in the isolated
 * admin console. This page intentionally has no mutation calls.
 */
export default function KllmPage() {
  const [status, setStatus] = useState<KllmStatus | null>(null);
  const [telemetry, setTelemetry] = useState<KllmTelemetry | null>(null);
  const [activity, setActivity] = useState<KllmActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const sessionId = useBrowserSessionId();
  const [sessionActive, setSessionActive] = useState(false);
  // Page/UI-access gate (§11.1): `kllm_page` controls only this dashboard
  // view. Fail-open during SSR/loading (features undefined → `enabled`), so
  // the dashboard renders first and swaps to the notice once flags load —
  // the same hydration contract as other gated pages.
  const { data: features } = usePlatformFeatures();
  const { status: pageStatus, message: pageMessage } = featureState(
    features,
    'kllm_page'
  );

  const statusController = useRef<AbortController | null>(null);
  const telemetryController = useRef<AbortController | null>(null);
  const statusInFlight = useRef(false);
  const telemetryInFlight = useRef(false);
  const statusBackoff = useRef(STATUS_INTERVAL_MS);
  const telemetryBackoff = useRef(TELEMETRY_INTERVAL_MS);
  const statusTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const telemetryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadActivity = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await api.getKllmActivity(20, signal);
      if (!signal?.aborted) setActivity(data.items);
    } catch {
      // Activity is supplementary; never block the dashboard on it.
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await api.getKllmStatus();
      setStatus(data);
      setError(null);
      await loadActivity();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRefreshing(false);
    }
  }, [loadActivity]);

  // Status polling: 15 s, paused while the tab is hidden, aborted on unmount,
  // never overlapping, exponential backoff on failures.
  useEffect(() => {
    let cancelled = false;

    function schedule(delay: number) {
      if (cancelled) return;
      statusTimer.current = setTimeout(tick, delay);
    }

    async function tick() {
      if (cancelled) return;
      if (document.hidden || statusInFlight.current) {
        schedule(statusBackoff.current);
        return;
      }
      statusInFlight.current = true;
      const controller = new AbortController();
      statusController.current = controller;
      try {
        const data = await api.getKllmStatus(controller.signal);
        if (cancelled || controller.signal.aborted) return;
        setStatus(data);
        setError(null);
        statusBackoff.current = STATUS_INTERVAL_MS;
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        setError(errorMessage(err));
        statusBackoff.current = Math.min(
          statusBackoff.current * 2,
          MAX_BACKOFF_MS,
        );
      } finally {
        statusInFlight.current = false;
        if (!cancelled) setLoading(false);
        schedule(statusBackoff.current);
      }
    }

    function onVisibilityChange() {
      if (document.hidden || cancelled) return;
      if (statusTimer.current) clearTimeout(statusTimer.current);
      void tick();
    }

    void tick();
    setTimeout(() => {
      void loadActivity();
    }, 0);
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (statusTimer.current) clearTimeout(statusTimer.current);
      statusController.current?.abort();
    };
  }, [loadActivity]);

  // Sanitized per-tab presence state. The layout owns the heartbeat; this
  // only reads the projected state for the user-facing explanation.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    const load = async () => {
      try {
        const value = await api.getKllmSessionStatus(sessionId);
        if (!cancelled) setSessionActive(value.active);
      } catch {
        if (!cancelled) setSessionActive(false);
      }
    };
    void load();
    const timer = setInterval(() => void load(), STATUS_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [sessionId]);

  const activeBackends = (status?.summary?.backends ?? 0) > 0;

  const sortedModels = useMemo(
    () =>
      [...(status?.models ?? [])].sort((a, b) => {
        const rankDiff = readinessRank(a.readiness) - readinessRank(b.readiness);
        if (rankDiff !== 0) return rankDiff;
        return a.key.localeCompare(b.key);
      }),
    [status?.models],
  );

  // Telemetry polling: 5 s, only while the page is visible and at least one
  // backend exists. No polling when kLLM is disabled/unreachable.
  useEffect(() => {
    if (!status?.enabled || !activeBackends) {
      queueMicrotask(() => setTelemetry(null));
      return;
    }
    let cancelled = false;

    function schedule(delay: number) {
      if (cancelled) return;
      telemetryTimer.current = setTimeout(tick, delay);
    }

    async function tick() {
      if (cancelled) return;
      if (document.hidden || telemetryInFlight.current) {
        schedule(telemetryBackoff.current);
        return;
      }
      telemetryInFlight.current = true;
      const controller = new AbortController();
      telemetryController.current = controller;
      try {
        const data = await api.getKllmTelemetry(controller.signal);
        if (cancelled || controller.signal.aborted) return;
        setTelemetry(data);
        telemetryBackoff.current = TELEMETRY_INTERVAL_MS;
      } catch {
        if (cancelled || controller.signal.aborted) return;
        telemetryBackoff.current = Math.min(
          telemetryBackoff.current * 2,
          30_000,
        );
      } finally {
        telemetryInFlight.current = false;
        schedule(telemetryBackoff.current);
      }
    }

    function onVisibilityChange() {
      if (document.hidden || cancelled) return;
      if (telemetryTimer.current) clearTimeout(telemetryTimer.current);
      void tick();
    }

    void tick();
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (telemetryTimer.current) clearTimeout(telemetryTimer.current);
      telemetryController.current?.abort();
    };
  }, [status?.enabled, activeBackends]);

  if (loading && !status) {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 flex flex-col items-center justify-center min-h-[50vh]">
        <LoaderIcon size={24} className="text-brand mb-2 animate-spin" />
        <span className="text-sm text-muted-foreground">Loading kLLM status...</span>
      </div>
    );
  }

  if (pageStatus !== 'enabled') {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable
          status={pageStatus}
          message={
            pageMessage ??
            "We're currently updating the real-time kLLM data visualization system. The kLLM dashboard view will be available soon."
          }
          title="kLLM dashboard"
          variant="page"
        />
      </div>
    );
  }

  const enabled = status?.enabled ?? false;
  const reachable = status?.reachable ?? false;
  const stale = status?.stale ?? false;

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <PageHeader
        title="kLLM"
        support="Local, server-owned inference. kLLM owns serving and lifecycle; Revora proxies a sanitized, read-only view and never exposes backend identities."
        icon={
          <Image
            src="/assets/kllm.svg"
            alt="kLLM"
            width={28}
            height={28}
            className="inline-flex rounded-md"
          />
        }
        actions={
          <div className="flex items-center gap-2">
            <Pill tone={!enabled ? 'muted' : stale ? 'warning' : reachable ? 'success' : 'error'} dot>
              {!enabled
                ? 'Disabled'
                : stale
                  ? 'Stale'
                  : reachable
                    ? 'Live'
                    : 'Unreachable'}
            </Pill>
            <button
              onClick={() => void refreshAll()}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-1 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-brand/40 disabled:opacity-50"
            >
              {refreshing ? (
                <LoaderIcon size={14} className="animate-spin" />
              ) : (
                <RefreshCwIcon size={14} />
              )}
              Refresh
            </button>
          </div>
        }
      />
      <SettingsShell />

      <div className="mb-6 rounded-xl border border-border bg-surface-1 p-4">
        <p className="text-sm text-muted-foreground">
          Model loading and lifecycle are managed by an administrator. If a model
          shows <span className="font-medium text-foreground">Not loaded</span>,
          it may load automatically when a review needs it, or an administrator
          can load it from the admin console.
        </p>
        <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Pill tone={sessionActive ? 'success' : 'muted'} dot>
            {sessionActive ? 'Session active' : 'Session idle'}
          </Pill>
          An active browser session may keep an approved model available. When
          you stop using Revora, kLLM still decides when to retire it; Revora
          never unloads models on your behalf.
        </p>
      </div>

      {/* State 3: the page-access flag is on, but the managed provider is
          disabled or under maintenance. The dashboard stays fully rendered;
          every string below is plain user-facing copy. */}
      {!enabled && (
        <div className="mb-6 rounded-xl border border-warning/30 bg-warning/5 p-5">
          <div className="flex items-start gap-3">
            <TriangleAlertIcon size={20} className="mt-0.5 text-warning" />
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-foreground">
                kLLM is disabled or under maintenance
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                The kLLM provider is currently disabled or under maintenance,
                so kLLM inference and reviews cannot be used right now.
              </p>
            </div>
          </div>
        </div>
      )}

      {enabled && error && (
        <div className="mb-6 rounded-xl border border-error/30 bg-error/5 p-4 text-sm text-error">
          {error}
        </div>
      )}

      {enabled && status?.error && (
        <div className="mb-6 rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm text-warning">
          {status.error}
        </div>
      )}

      {status && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <StatCard label="Backends" value={status.summary.backends} sub={`${status.summary.healthy_backends} healthy`} />
            <StatCard label="Ready models" value={status.summary.ready_models} sub={`${status.summary.loaded_models} loaded`} />
            <StatCard label="Sessions" value={status.summary.sessions} sub={`${status.summary.inflight} in flight`} />
            <StatCard
              label="Freshness"
              value={`${Math.round(status.age_seconds)}s`}
              sub={stale ? 'stale' : `updated ${timeAgo(status.generated_at)}`}
            />
          </div>

          <section className="mb-8">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h2 className="text-lg font-semibold text-foreground">Models</h2>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  {status.summary.loading_models} loading · {status.summary.failed_models} failed
                </span>
                <Pill tone="brand">{KLLM_MANAGEMENT_LABEL}</Pill>
              </div>
            </div>
            <div className="overflow-hidden rounded-xl border border-border bg-surface-1">
              {/* Desktop table */}
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-2/60 text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">Model</th>
                      <th className="px-4 py-2.5 font-medium">Readiness</th>
                      <th className="px-4 py-2.5 font-medium">Context</th>
                      <th className="px-4 py-2.5 font-medium">Backends</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedModels.map((model) => (
                      <tr key={model.key} className="border-t border-border/70">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2 min-w-0">
                            <ModelIcon
                              model={{ key: model.key, provider: KLLM_PROVIDER }}
                              size={15}
                              className="shrink-0"
                            />
                            <span className="truncate font-medium text-foreground" title={model.key}>
                              {modelDisplayName({ key: model.key })}
                            </span>
                            {model.vision && <Pill tone="info">Vision</Pill>}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <Pill tone={READINESS_TONE[model.readiness] ?? 'muted'} dot>
                            {READINESS_LABEL[model.readiness] ?? model.readiness}
                          </Pill>
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {model.context_window
                            ? `${Math.round(model.context_window / 1024)}K`
                            : '—'}
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {model.backend_count}
                        </td>
                      </tr>
                    ))}
                    {sortedModels.length === 0 && (
                      <tr>
                        <td colSpan={4} className="px-4 py-8 text-center text-sm text-muted-foreground">
                          No models reported by kLLM.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="md:hidden divide-y divide-border/70">
                {sortedModels.length === 0 ? (
                  <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                    No models reported by kLLM.
                  </div>
                ) : (
                  sortedModels.map((model) => (
                    <div key={model.key} className="px-4 py-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <ModelIcon
                              model={{ key: model.key, provider: KLLM_PROVIDER }}
                              size={15}
                              className="shrink-0"
                            />
                          <span
                            className="truncate font-medium text-foreground"
                            title={model.key}
                          >
                            {modelDisplayName({ key: model.key })}
                          </span>
                        </div>
                        <Pill
                          tone={READINESS_TONE[model.readiness] ?? 'muted'}
                          dot
                          className="shrink-0"
                        >
                          {READINESS_LABEL[model.readiness] ?? model.readiness}
                        </Pill>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {model.vision && <Pill tone="info">Vision</Pill>}
                        <span>
                          Context:{' '}
                          {model.context_window
                            ? `${Math.round(model.context_window / 1024)}K`
                            : '—'}
                        </span>
                        <span>Backends: {model.backend_count}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>

          <section className="mb-8">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h2 className="text-lg font-semibold text-foreground">Backends</h2>
              <span className="text-xs text-muted-foreground">
                {status.summary.draining_backends} draining · {status.summary.pending_backends} pending
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3">
              {status.backends.map((backend, index) => (
                <div
                  key={`${backend.model ?? 'backend'}-${index}`}
                  className="rounded-xl border border-border bg-surface-1 p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <Pill tone={BACKEND_TONE[backend.state] ?? 'muted'} dot>
                        {backend.state}
                      </Pill>
                      <span className="truncate text-sm font-semibold text-foreground">
                        {backend.model ?? 'Unknown model'}
                      </span>
                      {backend.pinned && <Pill tone="brand">Pinned</Pill>}
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 text-xs">
                    <Metric label="Health" value={backend.healthy ? 'Healthy' : 'Unhealthy'} tone={backend.healthy ? 'success' : 'error'} />
                    <Metric label="Uptime" value={formatDuration(backend.up_s)} />
                    <Metric label="Session left" value={formatDuration(backend.left_s)} />
                    <Metric label="Idle" value={formatDuration(backend.idle_s)} />
                    <Metric label="Sessions" value={String(backend.sessions ?? 0)} />
                    <Metric label="In flight" value={String(backend.inflight ?? 0)} />
                    <Metric label="RPM" value={formatNumber(backend.rpm, 1)} />
                    <Metric label="Errors (5m)" value={String(backend.errors_5m)} tone={backend.errors_5m > 0 ? 'warning' : 'muted'} />
                    <Metric
                      label="Quota"
                      value={
                        backend.quota_used_h != null && backend.quota_limit_h != null
                          ? `${backend.quota_used_h}h / ${backend.quota_limit_h}h`
                          : '—'
                      }
                    />
                    <Metric
                      label="GPU"
                      value={
                        backend.gpu
                          ? `${formatMib(backend.gpu.used_mib)} / ${formatMib(backend.gpu.total_mib)}`
                          : '—'
                      }
                    />
                  </div>
                </div>
              ))}
              {status.backends.length === 0 && (
                <div className="rounded-xl border border-border bg-surface-1 p-8 text-center text-sm text-muted-foreground">
                  No backends are running. An administrator can load a model from
                  the admin console.
                </div>
              )}
            </div>

            {status.pending.length > 0 && (
              <div className="mt-3 rounded-xl border border-border bg-surface-1 p-4">
                <h3 className="text-xs font-semibold text-muted-foreground mb-2">
                  Starting
                </h3>
                <ul className="space-y-1.5 text-sm">
                  {status.pending.map((row, index) => (
                    <li
                      key={`${row.model ?? 'pending'}-${index}`}
                      className="flex items-center justify-between gap-3"
                    >
                      <span className="truncate text-foreground">{row.model ?? 'Unknown model'}</span>
                      <span className={`text-xs ${row.failed ? 'text-error' : 'text-muted-foreground'}`}>
                        {row.phase}
                        {row.age_s != null ? ` · ${formatDuration(row.age_s)}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section className="mb-8">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h2 className="text-lg font-semibold text-foreground">Telemetry</h2>
              <span className="text-xs text-muted-foreground">
                aggregate only · {telemetry ? `${Math.round(telemetry.age_seconds)}s old` : 'waiting'}
              </span>
            </div>
            <div className="rounded-xl border border-border bg-surface-1 p-4">
              {!telemetry ? (
                <p className="text-sm text-muted-foreground">
                  {activeBackends
                    ? 'Waiting for kLLM telemetry...'
                    : 'No active backends. Telemetry is not polled while idle.'}
                </p>
              ) : !telemetry.available ? (
                <p className="text-sm text-muted-foreground">
                  {telemetry.error ??
                    (telemetry.reason === 'no_active_backends'
                      ? 'No active backends to report.'
                      : 'Telemetry is unavailable.')}
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                    <StatCard label="GPU used" value={formatMib(telemetry.totals.gpu_used_mib)} sub={`of ${formatMib(telemetry.totals.gpu_total_mib)}`} />
                    <StatCard label="GPU util" value={telemetry.totals.gpu_util != null ? `${telemetry.totals.gpu_util}%` : '—'} sub={`${telemetry.totals.backends} backends`} />
                    <StatCard label="Sessions" value={telemetry.totals.sessions} sub={`${telemetry.totals.inflight} in flight`} />
                    <StatCard label="RPM" value={formatNumber(telemetry.totals.rpm, 1)} sub={stale ? 'stale' : 'live'} />
                  </div>
                  <div className="space-y-2">
                    {telemetry.gpus.map((gpu, index) => (
                      <div key={`${gpu.index ?? index}`} className="flex items-center gap-3 text-xs">
                        <span className="w-16 shrink-0 text-muted-foreground">GPU {gpu.index ?? index}</span>
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
                          <div
                            className="h-full rounded-full bg-brand"
                            style={{
                              width: `${Math.min(
                                100,
                                gpu.total_mib
                                  ? ((gpu.used_mib ?? 0) / gpu.total_mib) * 100
                                  : 0,
                              )}%`,
                            }}
                          />
                        </div>
                        <span className="w-40 shrink-0 text-right text-muted-foreground">
                          {formatMib(gpu.used_mib)} / {formatMib(gpu.total_mib)}
                          {gpu.util != null ? ` · ${gpu.util}%` : ''}
                          {gpu.temp != null ? ` · ${gpu.temp}°C` : ''}
                        </span>
                      </div>
                    ))}
                    {telemetry.gpus.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        kLLM did not report per-GPU counters.
                      </p>
                    )}
                  </div>
                  {telemetry.stale && (
                    <p className="mt-3 text-xs text-warning">
                      Showing the last good sample; kLLM telemetry is currently stale.
                    </p>
                  )}
                </>
              )}
            </div>
          </section>

          <section className="mb-8">
            <h2 className="text-lg font-semibold text-foreground mb-3">Your review activity</h2>
            <div className="rounded-xl border border-border bg-surface-1 overflow-hidden">
              {activity.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">
                  No kLLM review executions yet. Review activity comes from
                  Revora&apos;s own execution records, never from kLLM&apos;s request log.
                </p>
              ) : (
                <ul className="divide-y divide-border/70">
                  {activity.map((item) => (
                    <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-medium text-foreground">
                            {item.repository_full_name ?? 'Repository'}
                            {item.pr_number != null ? ` #${item.pr_number}` : ''}
                          </span>
                          <Pill
                            tone={
                              item.status === 'completed'
                                ? 'success'
                                : item.status === 'failed'
                                  ? 'error'
                                  : 'warning'
                            }
                          >
                            {item.status}
                          </Pill>
                        </div>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {item.model ?? 'Unknown model'}
                          {item.started_at ? ` · ${timeAgo(item.started_at)}` : ''}
                          {item.duration_ms != null
                            ? ` · ${(item.duration_ms / 1000).toFixed(1)}s`
                            : ''}
                          {item.total_tokens != null
                            ? ` · ${item.total_tokens.toLocaleString()} tokens`
                            : ''}
                        </p>
                      </div>
                      {item.has_error && (
                        <Pill tone="error">
                          <TriangleAlertIcon size={11} /> Error
                        </Pill>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </>
      )}

      <footer className="mt-12 border-t border-border pt-6 text-center text-xs text-muted-foreground">
        &copy; {new Date().getFullYear()} Revora. All rights reserved.
      </footer>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface-1 p-4">
      <p className="text-xs font-medium text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-xl font-bold text-foreground">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function Metric({
  label,
  value,
  tone = 'muted',
}: {
  label: string;
  value: string;
  tone?: 'muted' | 'success' | 'warning' | 'error';
}) {
  const toneClass =
    tone === 'success'
      ? 'text-success'
      : tone === 'warning'
        ? 'text-warning'
        : tone === 'error'
          ? 'text-error'
          : 'text-foreground';
  return (
    <div>
      <span className="block text-[11px] text-muted-foreground">
        {label}
      </span>
      <span className={`block font-medium ${toneClass}`}>{value}</span>
    </div>
  );
}
