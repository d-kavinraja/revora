'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import {
  RefreshCwIcon,
  TriangleAlertIcon,
  PinIcon,
  PlayIcon,
  RotateCwIcon,
  SquareIcon,
} from 'lucide-react';
import { api, KllmActivityItem, KllmStatus, KllmTelemetry } from '@/lib/api';
import { useAuthStore } from '@/store/useAuthStore';
import { useToast } from '@/components/ui/toaster';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { ProviderIcon } from '@/components/ui/provider-icon';
import { Pill, type PillTone } from '@/components/shared/pill';
import { timeAgo } from '@/components/shared/time-ago';

const STATUS_INTERVAL_MS = 15_000;
const TELEMETRY_INTERVAL_MS = 5_000;
const MAX_BACKOFF_MS = 60_000;

const BACKEND_TONE: Record<string, PillTone> = {
  running: 'success',
  draining: 'warning',
  retiring: 'warning',
  unhealthy: 'error',
};

const MODEL_TONE: Record<string, PillTone> = {
  loaded: 'success',
  loading: 'warning',
  failed: 'error',
  unloaded: 'muted',
};

type ConfirmState = {
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => Promise<void>;
} | null;

function errorMessage(err: unknown): string {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: unknown } } }).response;
    const detail = response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
  }
  if (err instanceof Error && err.message) return err.message;
  return 'Unexpected error.';
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  const total = Math.max(0, Math.floor(seconds));
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

export default function KllmPage() {
  const { toast } = useToast();
  const role = useAuthStore((s) => s.user?.role);
  const isAdmin = role === 'admin';

  const [status, setStatus] = useState<KllmStatus | null>(null);
  const [telemetry, setTelemetry] = useState<KllmTelemetry | null>(null);
  const [activity, setActivity] = useState<KllmActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmState>(null);
  const [keepSize, setKeepSize] = useState(0);

  const mounted = useRef(true);
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
    setBusy('refresh');
    try {
      const data = isAdmin
        ? await api.kllmRefresh()
        : await api.getKllmStatus();
      setStatus(data);
      setError(null);
      await loadActivity();
    } catch (err) {
      toast({
        title: 'Refresh failed',
        description: errorMessage(err),
        type: 'error',
      });
    } finally {
      setBusy(null);
    }
  }, [isAdmin, loadActivity, toast]);

  // Status polling: 15 s, paused while the tab is hidden, aborted on unmount,
  // never overlapping, exponential backoff on failures.
  useEffect(() => {
    mounted.current = true;
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
        const data = await api.getKllmStatus(false, controller.signal);
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
    // Deferred so activity loading cannot be seen as synchronous setState.
    setTimeout(() => {
      void loadActivity();
    }, 0);
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      cancelled = true;
      mounted.current = false;
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (statusTimer.current) clearTimeout(statusTimer.current);
      statusController.current?.abort();
    };
  }, [loadActivity]);

  const activeBackends = (status?.summary?.backends ?? 0) > 0;

  // Telemetry polling: 5 s, only while the page is visible and at least one
  // backend exists. No polling when kLLM is disabled/unreachable.
  useEffect(() => {
    if (!status?.enabled || !activeBackends) {
      // Defer the reset so the effect body stays free of synchronous setState.
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

  const runAction = async (
    key: string,
    action: () => Promise<unknown>,
    successTitle: string,
  ) => {
    setBusy(key);
    try {
      await action();
      toast({ title: successTitle, type: 'success' });
      await refreshAll();
    } catch (err) {
      toast({
        title: 'Action failed',
        description: errorMessage(err),
        type: 'error',
      });
    } finally {
      setBusy(null);
    }
  };

  const requestLoad = (model: string) => {
    setConfirm({
      title: `Load ${model}?`,
      description:
        'kLLM will start a new backend for this model. It can take several minutes before it becomes ready, and it may consume GPU quota on the kLLM host.',
      confirmLabel: 'Load model',
      onConfirm: () =>
        runAction(
          `load:${model}`,
          () => api.kllmLoadModel(model, true),
          'Load requested',
        ),
    });
  };

  const requestStop = (id: string, models: string[]) => {
    setConfirm({
      title: 'Stop this backend?',
      description: `This stops every model and in-flight request served by this backend${
        models.length ? ` (${models.join(', ')})` : ''
      }. This cannot be undone from Revora.`,
      confirmLabel: 'Stop backend',
      danger: true,
      onConfirm: () =>
        runAction(
          `stop:${id}`,
          () => api.kllmStopBackend(id, true),
          'Stop requested',
        ),
    });
  };

  const requestRotate = (id: string, model: string | null) => {
    setConfirm({
      title: 'Rotate this backend?',
      description: `kLLM will start a fresh backend${
        model ? ` for ${model}` : ''
      }, hand sessions over, then stop the old one. Capacity is briefly reduced during the hand-off.`,
      confirmLabel: 'Rotate backend',
      onConfirm: () =>
        runAction(
          `rotate:${id}`,
          () => api.kllmRotateBackend(id, true),
          'Rotation requested',
        ),
    });
  };

  const applyKeep = () => {
    if (keepSize === 0) {
      void runAction(
        'keep',
        () => api.kllmSetKeep(0, false),
        'Always-on pool disabled',
      );
      return;
    }
    setConfirm({
      title: `Keep ${keepSize} model(s) always on?`,
      description:
        'kLLM will maintain this many backends around the clock and auto-rotate them before the session cap. This consumes GPU quota continuously.',
      confirmLabel: 'Enable always-on',
      onConfirm: () =>
        runAction(
          'keep',
          () => api.kllmSetKeep(keepSize, true),
          'Always-on pool updated',
        ),
    });
  };

  if (loading && !status) {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 flex flex-col items-center justify-center min-h-[50vh]">
        <LoaderIcon size={24} className="text-brand mb-2 animate-spin" />
        <span className="text-sm text-muted-foreground">Loading kLLM status...</span>
      </div>
    );
  }

  const enabled = status?.enabled ?? false;
  const reachable = status?.reachable ?? false;
  const stale = status?.stale ?? false;

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Image
              src="/assets/kllm.svg"
              alt="kLLM"
              width={28}
              height={28}
              className="inline-flex rounded-md"
            />
            kLLM
          </h1>
          <p className="mt-1 text-muted-foreground text-sm">
            Local, server-owned inference. kLLM owns serving and lifecycle; Revora
            proxies a sanitized view and never exposes backend identities.
          </p>
        </div>
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
            disabled={busy === 'refresh'}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-1 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-brand/40 disabled:opacity-50"
          >
            {busy === 'refresh' ? (
              <LoaderIcon size={14} className="animate-spin" />
            ) : (
              <RefreshCwIcon size={14} />
            )}
            Refresh
          </button>
        </div>
      </div>

      {!enabled && (
        <div className="mb-6 rounded-xl border border-border bg-surface-1 p-5">
          <div className="flex items-start gap-3">
            <TriangleAlertIcon size={20} className="mt-0.5 text-warning" />
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-foreground">
                kLLM is disabled
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                The managed provider is off. Enable it in two places: set{' '}
                <code className="rounded bg-surface-2 px-1 py-0.5 text-xs">
                  KLLM_ENABLED=true
                </code>{' '}
                in <code className="text-xs">backend/.env</code> and restart the
                backend, then enable the <strong>kLLM</strong> provider in
                Settings &rarr; Providers. Until both are done, routing,
                repository mapping, reviews and this dashboard stay gated.
              </p>
              {status?.configured === false && (
                <p className="mt-2 text-xs text-muted-foreground">
                  The managed provider row is missing. Run{' '}
                  <code className="text-xs">alembic upgrade head</code>.
                </p>
              )}
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

      {enabled && status && (
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
              <span className="text-xs text-muted-foreground">
                {status.summary.loading_models} loading · {status.summary.failed_models} failed
              </span>
            </div>
            <div className="overflow-hidden rounded-xl border border-border bg-surface-1">
              <table className="w-full text-sm">
                <thead className="bg-surface-2/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Model</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                    <th className="px-4 py-2.5 font-medium">Context</th>
                    <th className="px-4 py-2.5 font-medium">Backends</th>
                    <th className="px-4 py-2.5 font-medium text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {status.models.map((model) => (
                    <tr key={model.key} className="border-t border-border/70">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 min-w-0">
                          <ProviderIcon slug="kllm" size={15} />
                          <span className="truncate font-medium text-foreground" title={model.key}>
                            {model.key}
                          </span>
                          {model.vision && <Pill tone="info">Vision</Pill>}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <Pill tone={MODEL_TONE[model.status] ?? 'muted'} dot>
                          {model.status}
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
                      <td className="px-4 py-3 text-right">
                        {isAdmin && !model.ready && model.status !== 'loading' ? (
                          <button
                            onClick={() => requestLoad(model.key)}
                            disabled={busy === `load:${model.key}`}
                            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2.5 py-1 text-xs font-medium text-foreground hover:border-brand/40 disabled:opacity-50"
                          >
                            {busy === `load:${model.key}` ? (
                              <LoaderIcon size={12} className="animate-spin" />
                            ) : (
                              <PlayIcon size={12} />
                            )}
                            Load
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            {model.ready ? 'Ready' : model.status === 'loading' ? 'Loading' : '—'}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {status.models.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-sm text-muted-foreground">
                        No models reported by kLLM.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
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
              {status.backends.map((backend) => (
                <div
                  key={backend.id}
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
                      {backend.pinned && (
                        <Pill tone="brand">
                          <PinIcon size={11} /> Pinned
                        </Pill>
                      )}
                    </div>
                    {isAdmin && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <button
                          onClick={() =>
                            runAction(
                              `pin:${backend.id}`,
                              () => api.kllmPinBackend(backend.id, !backend.pinned),
                              backend.pinned ? 'Backend unpinned' : 'Backend pinned',
                            )
                          }
                          disabled={busy === `pin:${backend.id}`}
                          className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-2 px-2 py-1 text-xs font-medium text-foreground hover:border-brand/40 disabled:opacity-50"
                        >
                          <PinIcon size={11} />
                          {backend.pinned ? 'Unpin' : 'Pin'}
                        </button>
                        <button
                          onClick={() =>
                            requestRotate(backend.id, backend.model)
                          }
                          disabled={busy === `rotate:${backend.id}`}
                          className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-2 px-2 py-1 text-xs font-medium text-foreground hover:border-brand/40 disabled:opacity-50"
                        >
                          <RotateCwIcon size={11} />
                          Rotate
                        </button>
                        <button
                          onClick={() =>
                            requestStop(
                              backend.id,
                              backend.model ? [backend.model] : [],
                            )
                          }
                          disabled={busy === `stop:${backend.id}`}
                          className="inline-flex items-center gap-1 rounded-md border border-error/30 bg-error/10 px-2 py-1 text-xs font-medium text-error hover:border-error/50 disabled:opacity-50"
                        >
                          <SquareIcon size={11} />
                          Stop
                        </button>
                      </div>
                    )}
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
                  No backends are running. Load a model to start one.
                </div>
              )}
            </div>

            {status.pending.length > 0 && (
              <div className="mt-3 rounded-xl border border-border bg-surface-1 p-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                  Starting
                </h3>
                <ul className="space-y-1.5 text-sm">
                  {status.pending.map((row) => (
                    <li key={row.id} className="flex items-center justify-between gap-3">
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

          {isAdmin && (
            <section className="mb-8">
              <h2 className="text-lg font-semibold text-foreground mb-3">Always-on pool</h2>
              <div className="rounded-xl border border-border bg-surface-1 p-4">
                <p className="text-sm text-muted-foreground mb-3">
                  Keep a fixed number of backends running continuously. kLLM
                  auto-rotates them before the session cap. This consumes GPU
                  quota for as long as it is enabled.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="number"
                    min={0}
                    max={10}
                    value={keepSize}
                    onChange={(event) =>
                      setKeepSize(
                        Math.max(0, Math.min(10, Number(event.target.value) || 0)),
                      )
                    }
                    className="w-20 rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm text-foreground"
                    aria-label="Always-on pool size"
                  />
                  <button
                    onClick={applyKeep}
                    disabled={busy === 'keep'}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground hover:border-brand/40 disabled:opacity-50"
                  >
                    {busy === 'keep' && <LoaderIcon size={12} className="animate-spin" />}
                    Apply
                  </button>
                  <span className="text-xs text-muted-foreground">
                    0 disables always-on.
                  </span>
                </div>
              </div>
            </section>
          )}

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

      {confirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          role="dialog"
          aria-modal="true"
          aria-label={confirm.title}
        >
          <div className="w-full max-w-md rounded-xl border border-border bg-surface-1 p-5 shadow-xl">
            <h3 className="text-base font-semibold text-foreground">
              {confirm.title}
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {confirm.description}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setConfirm(null)}
                className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  const action = confirm;
                  setConfirm(null);
                  void action.onConfirm();
                }}
                className={`rounded-md px-3 py-1.5 text-xs font-medium text-white ${
                  confirm.danger ? 'bg-error hover:bg-error/90' : 'bg-brand hover:bg-brand-hover'
                }`}
              >
                {confirm.confirmLabel}
              </button>
            </div>
          </div>
        </div>
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
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
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
      <span className="block text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className={`block font-medium ${toneClass}`}>{value}</span>
    </div>
  );
}
