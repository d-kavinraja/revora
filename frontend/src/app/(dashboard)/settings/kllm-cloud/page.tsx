'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CloudLightning, RefreshCwIcon } from 'lucide-react';

import { api, type CloudModelStatus, type CloudStatus } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { ModelIcon } from '@/components/ui/model-icon';
import { Pill, type PillTone } from '@/components/shared/pill';
import { ManagedByRevora } from '@/components/shared/managed-by-revora';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { PageHeader } from '@/components/shared/page-header';
import { SettingsShell } from '@/components/shared/settings-shell';
import { formatContextWindow, CLOUD_PROVIDER, CLOUD_SUPPORT_DESCRIPTION } from '@/lib/chat-state';
import { surfaceLabel, surfaceStates } from '@/lib/cloud-status';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';

const STATUS_INTERVAL_MS = 20_000;
const MAX_BACKOFF_MS = 60_000;


function errorMessage(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const detail = (err as { response?: { data?: { detail?: unknown } } }).response
      ?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (typeof (err as Error).message === 'string') return (err as Error).message;
  }
  return 'Something went wrong. Please try again.';
}

function stateTone(status: CloudStatus | null): PillTone {
  if (!status || !status.enabled) return 'muted';
  if (!status.configured) return 'muted';
  if (status.stale) return 'warning';
  if (status.reachable) return 'success';
  return 'error';
}

function stateLabel(status: CloudStatus | null): string {
  if (!status) return 'Loading';
  if (!status.enabled) return 'Unavailable';
  if (!status.configured) return 'Not configured';
  if (status.stale) return 'Stale';
  return status.reachable ? 'Available' : 'Unreachable';
}

/** Why the model list is empty: never claim a failure the backend did not report. */
function emptyModelMessage(status: CloudStatus): string {
  if (!status.enabled) {
    return 'kLLM Cloud is not available right now. Ask an administrator to enable the provider.';
  }
  if (!status.reachable) {
    return 'kLLM Cloud cannot be reached right now, so no models are listed.';
  }
  return 'No kLLM Cloud models are approved for use yet. An administrator must approve a model before it can be used.';
}
/**
 * Read-only kLLM Cloud status for ordinary users.
 *
 * Model approval, per-surface availability and catalogue refresh are
 * administrator-only and live in the isolated admin console. This page only
 * shows which cloud models the user may currently use, and never exposes the
 * relay endpoint or credentials.
 */
export default function KllmCloudPage() {
  const [status, setStatus] = useState<CloudStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const { data: features } = usePlatformFeatures();
  const { status: pageStatus, message: pageMessage } = featureState(features, 'kllm_cloud_page');

  const controller = useRef<AbortController | null>(null);
  const backoff = useRef(STATUS_INTERVAL_MS);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await api.getCloudStatus();
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    // Per-effect-instance guard: a component-level ref survives StrictMode's
    // mount/unmount/mount cycle, so a request aborted by the first cleanup
    // would leave the flag set and delay the first status load by a full
    // polling interval (20s) on an otherwise empty page.
    let inFlight = false;

    function schedule(delay: number) {
      if (cancelled) return;
      timer.current = setTimeout(tick, delay);
    }

    async function tick() {
      if (cancelled) return;
      if (document.hidden || inFlight) {
        schedule(backoff.current);
        return;
      }
      inFlight = true;
      const next = new AbortController();
      controller.current = next;
      try {
        const data = await api.getCloudStatus(next.signal);
        if (cancelled || next.signal.aborted) return;
        setStatus(data);
        setError(null);
        backoff.current = STATUS_INTERVAL_MS;
      } catch (err) {
        if (cancelled || next.signal.aborted) return;
        setError(errorMessage(err));
        backoff.current = Math.min(backoff.current * 2, MAX_BACKOFF_MS);
      } finally {
        inFlight = false;
        if (!cancelled) setLoading(false);
        schedule(backoff.current);
      }
    }

    function onVisibilityChange() {
      if (document.hidden || cancelled) return;
      if (timer.current) clearTimeout(timer.current);
      void tick();
    }

    void tick();
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (timer.current) clearTimeout(timer.current);
      controller.current?.abort();
    };
  }, []);

  const models = useMemo<CloudModelStatus[]>(() => status?.models ?? [], [status?.models]);

  if (loading && !status) {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 flex flex-col items-center justify-center min-h-[50vh]">
        <LoaderIcon size={24} className="text-brand mb-2 animate-spin" />
        <span className="text-sm text-muted-foreground">Loading kLLM Cloud status...</span>
      </div>
    );
  }

  if (pageStatus !== 'enabled') {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable
          status={pageStatus}
          message={pageMessage ?? 'kLLM Cloud is temporarily unavailable while we update the service.'}
          title="kLLM Cloud"
          variant="page"
        />
      </div>
    );
  }

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <PageHeader
        title="kLLM Cloud"
        support={CLOUD_SUPPORT_DESCRIPTION}
        icon={<CloudLightning size={28} className="text-foreground" aria-hidden />}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <ManagedByRevora size="xs" className="shrink-0" />
            <Pill tone={stateTone(status)} dot>{stateLabel(status)}</Pill>
            <button
              onClick={() => void refresh()}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-1 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-brand/40 disabled:opacity-50"
            >
              {refreshing ? <LoaderIcon size={14} className="animate-spin" /> : <RefreshCwIcon size={14} />}
              Refresh
            </button>
          </div>
        }
      />
      <SettingsShell />

      <div className="mb-6 rounded-xl border border-border bg-surface-1 p-4">
        <p className="text-sm text-muted-foreground">
          kLLM Cloud is an independent managed provider. An administrator approves
          each model, and Chat and Reviews are enabled separately. A model that is
          not approved here cannot be selected in Chat or used for a review.
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-error/30 bg-error/10 px-3 py-2 text-sm text-error">
          {error}
        </div>
      )}

      {models.length === 0 && status && (
        <div className="rounded-xl border border-border bg-surface-1 p-6 text-center text-sm text-muted-foreground">
          {emptyModelMessage(status)}
        </div>
      )}
      {models.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-border bg-surface-1">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-surface-2/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Model</th>
                <th className="px-4 py-2 font-medium">Context</th>
                <th className="px-4 py-2 font-medium">Available for</th>
                <th className="px-4 py-2 font-medium">Readiness</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {models.map((model) => {
                const context = formatContextWindow(model.context_window);
                // One pill per surface: Chat and Reviews are independent,
                // so a single combined status would be misleading.
                const states = surfaceStates(model);
                return (
                  <tr key={model.key}>
                    <td className="px-4 py-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <ModelIcon
                          model={{
                            key: model.key,
                            display_name: model.display_name,
                            provider: CLOUD_PROVIDER,
                            category: CLOUD_PROVIDER,
                          }}
                          size={16}
                          className="shrink-0"
                        />
                        <span className="truncate font-medium text-foreground" title={model.model_id}>
                          {model.display_name}
                        </span>
                        {model.vision && <Pill tone="info">Vision</Pill>}
                      </div>
                      {model.description && (
                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{model.description}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{context ?? '—'}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Pill tone={model.chat_enabled ? 'success' : 'muted'}>
                          {model.chat_enabled ? 'Chat' : 'No chat'}
                        </Pill>
                        <Pill tone={model.review_enabled ? 'success' : 'muted'}>
                          {model.review_enabled ? 'Reviews' : 'No reviews'}
                        </Pill>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {states.map((item) => (
                          <Pill key={item.surface} tone={item.tone} dot>
                            {surfaceLabel(item)}
                          </Pill>
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 text-xs text-muted-foreground">
        Model availability is confirmed by the provider and can change without notice.
        If a model stops working, refresh this page.
      </p>
    </div>
  );
}