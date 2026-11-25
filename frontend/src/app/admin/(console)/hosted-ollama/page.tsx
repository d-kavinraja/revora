'use client';

import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PowerIcon, RefreshCwIcon } from 'lucide-react';
import { adminApi, type AdminHostedModel } from '@/lib/api';
import { apiErrorMessage, isApiTransportError } from '@/lib/api-transport';
import { AdminPage, AdminSection } from '@/components/admin/page-shell';
import { StatusRibbon } from '@/components/admin/metrics';
import { AdminButton, AdminSwitch } from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';
import { Pill, type PillTone } from '@/components/shared/pill';
import { ModelIcon } from '@/components/ui/model-icon';
import { ProviderIcon } from '@/components/ui/provider-icon';
import { useToast } from '@/components/ui/toaster';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { HOSTED_PROVIDER, modelDisplayName, REVORA_MANAGEMENT_LABEL } from '@/lib/chat-state';
import { HostedTabs } from './hosted-tabs';

const REFRESH_INTERVAL_MS = 15_000;

function errorMessage(err: unknown): string {
  return apiErrorMessage(err) ?? 'Something went wrong. Please try again.';
}

const READINESS_TONE: Record<string, PillTone> = {
  ready: 'success',
  loading: 'warning',
  unloaded: 'muted',
  failed: 'error',
  unavailable: 'error',
  stale: 'warning',
};

export default function AdminHostedOllamaPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['admin', 'hosted-ollama'],
    queryFn: () => adminApi.hostedOllama(),
    refetchInterval: REFRESH_INTERVAL_MS,
    retry: false,
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['admin', 'hosted-ollama'] });
  };

  const selection = useMutation({
    mutationFn: (enabled: boolean) => adminApi.setHostedSelection(enabled),
    onSuccess: async (_result, enabled) => {
      toast({
        title: enabled ? 'Hosted models enabled' : 'Hosted models disabled',
        type: 'success',
      });
      await invalidate();
    },
    onError: (err) => {
      toast({
        title: isApiTransportError(err) ? 'Cannot reach the backend' : 'Update failed',
        description: errorMessage(err),
        type: 'error',
      });
    },
  });

  const refresh = useMutation({
    mutationFn: () => adminApi.refreshHosted(),
    onSuccess: async () => {
      toast({ title: 'Catalog refreshed', type: 'success' });
      await invalidate();
    },
    onError: (err) => {
      toast({ title: 'Refresh failed', description: errorMessage(err), type: 'error' });
    },
  });

  const wake = useMutation({
    mutationFn: () => adminApi.wakeHosted(),
    onSuccess: async () => {
      toast({ title: 'Wake requested', type: 'success' });
      await invalidate();
    },
    onError: (err) => {
      toast({ title: 'Wake failed', description: errorMessage(err), type: 'error' });
    },
  });

  const models = useMemo(() => data?.models ?? [], [data?.models]);

  if (isPending) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderIcon size={22} className="text-brand" animate />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <AdminPage
        eyebrow="System"
        title="Hosted models"
        description="Revora-managed remote inference for Chat."
      >
        <HostedTabs />
        <QueryError message={errorMessage(error)} onRetry={() => void refetch()} />
      </AdminPage>
    );
  }

  const connectionLabel = !data.enabled
    ? 'Disabled'
    : data.stale
      ? 'Stale'
      : data.reachable
        ? 'Live'
        : 'Unreachable';

  return (
    <AdminPage
      eyebrow="System"
      icon={<ProviderIcon slug="ollama" size={28} />}
      title="Hosted models"
      description="Revora-managed Ollama inference for Chat only. Only runtime-loaded models are exposed; Revora never auto-loads a model just to list it, and never substitutes a model. Disabling hosted models does not affect kLLM."
      actions={
        <AdminButton
          onClick={() => refresh.mutate()}
          disabled={isFetching || refresh.isPending}
          variant="secondary"
          size="sm"
        >
          {refresh.isPending ? (
            <LoaderIcon size={14} className="animate-spin" />
          ) : (
            <RefreshCwIcon size={14} />
          )}
          Refresh catalog
        </AdminButton>
      }
    >
      <HostedTabs />
      <StatusRibbon
        label="Runtime state"
        verdict={connectionLabel}
        hint={
          data.wake.waking
            ? 'A wake request is in flight.'
            : data.version
              ? `Running Ollama ${data.version}.`
              : 'The Ollama version is not recorded.'
        }
        readouts={[
          {
            key: 'models',
            label: 'Loaded models',
            value: String(models.length),
          },
          {
            key: 'inflight',
            label: 'In flight',
            value: String(data.concurrency.inflight),
            sub: `${data.concurrency.queued} queued`,
          },
          {
            key: 'version',
            label: 'Ollama version',
            value: data.version ?? 'Not recorded',
          },
        ]}
      />
      <AdminSection
        title="Selection"
        subtitle="Allow users to select hosted models in Chat. Enforced by the backend; the environment flag must also be enabled."
      >
        <AdminSwitch
          checked={data.selection_enabled}
          onChange={(next) => selection.mutate(next)}
          disabled={selection.isPending || !data.env_enabled}
          title="Enable hosted model selection"
          description={
            data.env_enabled
              ? 'When off, hosted models are hidden from Chat and rejected server-side. kLLM is unaffected.'
              : 'The backend environment flag (REVORA_HOSTED_OLLAMA_ENABLED) is off, so hosted models cannot be enabled here.'
          }
        />
        {!data.configured ? (
          <p className="mt-3 text-xs text-warning">
            No hosted endpoint is configured. Set REVORA_HOSTED_OLLAMA_BASE_URL in the backend environment.
          </p>
        ) : null}
        {data.error ? (
          <p className="mt-3 text-xs text-error">{data.error}</p>
        ) : null}
      </AdminSection>

      <AdminSection
        title="Connection & wake"
        subtitle="Revora only wakes the machine and holds an activity lease; it never changes the remote Ollama binding."
        actions={
          data.wake.enabled ? (
            <AdminButton
              onClick={() => wake.mutate()}
              disabled={wake.isPending || data.wake.waking}
              variant="secondary"
              size="sm"
            >
              {wake.isPending ? (
                <LoaderIcon size={14} className="animate-spin" />
              ) : (
                <PowerIcon size={14} />
              )}
              Wake machine
            </AdminButton>
          ) : undefined
        }
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Endpoint configured</span>
            <span className="text-sm font-medium text-foreground">
              {data.configured ? 'Yes' : 'No'}
            </span>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Reachable</span>
            <span className="text-sm font-medium text-foreground">
              {data.reachable ? 'Yes' : 'No'}
            </span>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Wake</span>
            <span className="text-sm font-medium text-foreground">
              {data.wake.enabled ? (data.wake.configured ? 'Enabled' : 'Enabled (not configured)') : 'Disabled'}
            </span>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Coordination</span>
            <span className="text-sm font-medium text-foreground">
              {data.concurrency.distributed ? 'Distributed (Redis)' : 'In-process'}
            </span>
          </div>
        </div>
        {data.wake.last_error ? (
          <p className="mt-3 text-xs text-error">{data.wake.last_error}</p>
        ) : null}
      </AdminSection>

      <AdminSection
        title="Concurrency"
        subtitle="Global and per-model caps with a bounded queue. Every permit is released on success, error, timeout and cancellation."
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Global cap</span>
            <span className="text-sm font-medium tabular-nums text-foreground">
              {data.concurrency.max_concurrent_requests}
            </span>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Per-model cap</span>
            <span className="text-sm font-medium tabular-nums text-foreground">
              {data.concurrency.max_concurrent_requests_per_model}
            </span>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Queue timeout</span>
            <span className="text-sm font-medium tabular-nums text-foreground">
              {data.concurrency.queue_timeout_s}s
            </span>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">In flight / queued</span>
            <span className="text-sm font-medium tabular-nums text-foreground">
              {data.concurrency.inflight} / {data.concurrency.queued}
            </span>
          </div>
        </div>
      </AdminSection>

      <AdminSection
        title="Runtime-loaded models"
        subtitle="Discovered from Ollama /api/ps. Downloaded-but-unloaded models are never listed."
        actions={<Pill tone="brand">{REVORA_MANAGEMENT_LABEL}</Pill>}
      >
        {models.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No models are currently loaded on the hosted runtime.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Model</th>
                  <th className="py-2 pr-4 font-medium">Readiness</th>
                  <th className="py-2 pr-4 font-medium">Context</th>
                  <th className="py-2 pr-4 font-medium">Tags</th>
                </tr>
              </thead>
              <tbody>
                {models.map((model: AdminHostedModel) => {
                  const identity = {
                    key: model.key,
                    display_name: model.model,
                    provider: HOSTED_PROVIDER,
                    category: 'hosted',
                  };
                  return (
                    <tr key={model.key} className="border-b border-border/60 last:border-0">
                      <td className="py-2.5 pr-4">
                        <span className="flex min-w-0 items-center gap-2 font-medium text-foreground">
                          <ModelIcon model={identity} size={16} className="shrink-0" />
                          <span className="min-w-0 truncate" title={model.key}>
                            {modelDisplayName(identity)}
                          </span>
                        </span>
                      </td>
                      <td className="py-2.5 pr-4">
                        <Pill tone={READINESS_TONE[model.readiness] ?? 'muted'}>
                          {model.readiness}
                        </Pill>
                      </td>
                      <td className="py-2.5 pr-4 tabular-nums text-muted-foreground">
                        {model.context_window
                          ? `${Math.round(model.context_window / 1024)}K`
                          : '—'}
                      </td>
                      <td className="py-2.5 pr-4 text-xs text-muted-foreground">
                        {model.tags.length ? model.tags.join(', ') : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </AdminSection>
    </AdminPage>
  );
}
