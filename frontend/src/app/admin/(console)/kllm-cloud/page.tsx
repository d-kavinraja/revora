'use client';

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCwIcon, ThermometerSun } from 'lucide-react';

import {
  adminApi,
  type AdminCloudModel,
  type AdminCloudModelUpdate,
} from '@/lib/api';
import { apiErrorMessage, isApiTransportError } from '@/lib/api-transport';
import { AdminPage, AdminSection } from '@/components/admin/page-shell';
import { StatusRibbon } from '@/components/admin/metrics';
import { AdminButton, FilterBar, SelectFilter } from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { Pill, type PillTone } from '@/components/shared/pill';
import { ManagedByRevora } from '@/components/shared/managed-by-revora';
import { ModelIcon } from '@/components/ui/model-icon';
import { ProviderIcon } from '@/components/ui/provider-icon';
import { useToast } from '@/components/ui/toaster';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { CLOUD_PROVIDER } from '@/lib/chat-state';

const REFRESH_INTERVAL_MS = 20_000;

function errorMessage(err: unknown): string {
  return apiErrorMessage(err) ?? 'Something went wrong. Please try again.';
}

const CLASSIFICATION_TONE: Record<string, PillTone> = {
  chat: 'success',
  media: 'info',
  alias: 'muted',
  unknown: 'warning',
};

const REASON_TEXT: Record<string, string> = {
  ready: 'Ready',
  not_approved: 'Not approved',
  chat_not_enabled: 'Chat off',
  review_not_enabled: 'Reviews off',
  model_disabled: 'Disabled',
  model_removed: 'Removed upstream',
  kllm_cloud_disabled: 'Provider off',
  kllm_cloud_unreachable: 'Unreachable',
  kllm_cloud_catalog_stale: 'Stale catalogue',
};

function ToggleButton({
  active,
  label,
  onClick,
  disabled,
  title,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <AdminButton
      size="sm"
      variant={active ? 'successSoft' : 'secondary'}
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-pressed={active}
    >
      {label}
    </AdminButton>
  );
}

function Readout({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
      <span className="block text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums text-foreground">{value}</span>
      {sub ? <span className="mt-0.5 block text-xs text-muted-foreground">{sub}</span> : null}
    </div>
  );
}

export default function AdminKllmCloudPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [scope, setScope] = useState<'chat' | 'all'>('chat');
  // Revocation removes the approval and therefore the model's Chat/Review
  // availability, so it is confirmed before anything is sent.
  const [revokeTarget, setRevokeTarget] = useState<AdminCloudModel | null>(null);

  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['admin', 'kllm-cloud'],
    queryFn: () => adminApi.kllmCloud(),
    refetchInterval: REFRESH_INTERVAL_MS,
    retry: false,
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['admin', 'kllm-cloud'] });
  };

  const refresh = useMutation({
    mutationFn: () => adminApi.refreshKllmCloud(),
    onSuccess: async (result) => {
      toast({
        title: result.refreshed ? 'Catalogue refreshed' : 'Refresh throttled',
        description: result.refreshed
          ? `${result.advertised ?? 0} models advertised by the provider.`
          : 'A refresh already ran recently. Try again in a moment.',
        type: result.refreshed ? 'success' : 'error',
      });
      await invalidate();
    },
    onError: (err) => {
      toast({ title: 'Refresh failed', description: errorMessage(err), type: 'error' });
    },
  });

  const probe = useMutation({
    mutationFn: () => adminApi.probeKllmCloud(),
    onSuccess: async (result) => {
      toast({
        title: 'Warm probe complete',
        description: `Backend warm state: ${result.backend_warm?.state ?? 'unknown'}.`,
        type: 'success',
      });
      await invalidate();
    },
    onError: (err) => {
      toast({ title: 'Warm probe failed', description: errorMessage(err), type: 'error' });
    },
  });

  const update = useMutation({
    mutationFn: ({
      modelId,
      patch,
    }: {
      modelId: string;
      patch: AdminCloudModelUpdate;
    }) => adminApi.updateKllmCloudModel(modelId, patch),
    onSuccess: async () => {
      toast({ title: 'Model updated', type: 'success' });
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

  const models = useMemo(() => data?.models ?? [], [data?.models]);
  const visible = useMemo(
    () => (scope === 'chat' ? models.filter((m) => m.classification === 'chat') : models),
    [models, scope],
  );
  const pendingModelId = update.isPending ? (update.variables?.modelId ?? null) : null;

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
        title="kLLM Cloud"
        description="Independent managed provider for Chat and Reviews."
      >
        <QueryError message={errorMessage(error)} onRetry={() => void refetch()} />
      </AdminPage>
    );
  }

  const warm = data.backend_warm;
  const verdict = !data.enabled
    ? 'Disabled'
    : !data.configured
      ? 'Not configured'
      : data.stale
        ? 'Stale'
        : data.reachable
          ? 'Ready'
          : 'Unreachable';

  const approve = (model: AdminCloudModel, next: boolean) => {
    if (!next) {
      setRevokeTarget(model);
      return;
    }
    update.mutate({ modelId: model.model_id, patch: { approved: true } });
  };

  return (
    <AdminPage
      eyebrow="System"
      icon={<ProviderIcon slug="kllm-cloud" size={28} />}
      title="kLLM Cloud"
      description="Independent managed provider for Chat and Reviews. Only models approved here are visible to users, and Chat and Reviews are enabled per model. Discovery uses the providers model list; nothing here runs inference."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <AdminButton
            onClick={() => probe.mutate()}
            disabled={probe.isPending}
            variant="secondary"
            size="sm"
          >
            {probe.isPending ? (
              <LoaderIcon size={14} className="animate-spin" />
            ) : (
              <ThermometerSun size={14} />
            )}
            Warm probe
          </AdminButton>
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
            Refresh catalogue
          </AdminButton>
        </div>
      }
    >
      <StatusRibbon
        label="Provider state"
        verdict={verdict}
        hint={data.reason || 'No provider error is reported.'}
        readouts={[
          { key: 'chat', label: 'Canonical chat', value: String(data.counts.canonical_chat ?? 0) },
          { key: 'media', label: 'Media', value: String(data.counts.media ?? 0) },
          { key: 'aliases', label: 'Aliases', value: String(data.counts.aliases ?? 0) },
          {
            key: 'approved',
            label: 'Approved',
            value: String(data.counts.approved ?? 0),
            sub: `${data.counts.disabled ?? 0} disabled`,
          },
        ]}
      />
      <AdminSection
        title="Provider"
        subtitle="Read-only provider state. Enabling or disabling the provider itself stays on the Providers page and the server environment flag."
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Readout label="Enabled" value={data.enabled ? 'Yes' : 'No'} />
          <Readout label="Endpoint configured" value={data.configured ? 'Yes' : 'No'} />
          <Readout
            label="Credential configured"
            value={data.credential_configured ? 'Yes' : 'No'}
          />
          <Readout label="Reachable" value={data.reachable ? 'Yes' : 'No'} />
          <Readout
            label="Catalogue age"
            value={
              data.catalog_age_seconds == null
                ? 'Not loaded'
                : `${Math.round(data.catalog_age_seconds)}s ago`
            }
          />
          <Readout
            label="Last successful sync"
            value={data.last_success_at ? new Date(data.last_success_at).toLocaleString() : 'Never'}
          />
          <Readout label="Concurrency limit" value={String(data.concurrency_limit)} />
          <Readout label="Queue timeout" value={`${data.queue_timeout_seconds}s`} />
        </div>
        {data.error ? <p className="mt-3 text-xs text-error">{data.error}</p> : null}
        <p className="mt-3 text-xs text-muted-foreground">
          Approval, Chat and Review availability are enforced by the backend on
          every request, so a stale view here can never grant access.
        </p>
      </AdminSection>

      <AdminSection
        title="Backend warm probe"
        subtitle="The health endpoint only reports whether some model backend is warm. It is not provider liveness, and it is never used to claim a specific model is loaded."
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Readout label="State" value={warm?.state ?? 'unknown'} />
          <Readout
            label="Checked"
            value={warm?.checked_at ? new Date(warm.checked_at).toLocaleTimeString() : 'Never'}
          />
          <Readout label="Detail" value={warm?.detail ?? '—'} />
        </div>
      </AdminSection>

      <AdminSection
        title="Catalogue reconciliation"
        subtitle="Every advertised identifier is classified. Aliases resolve to a canonical chat model, and media identifiers are never selectable by users."
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Readout label="Advertised" value={String(models.length)} />
          <Readout label="Canonical chat" value={String(data.counts.canonical_chat ?? 0)} />
          <Readout label="Media" value={String(data.counts.media ?? 0)} />
          <Readout label="Aliases" value={String(data.counts.aliases ?? 0)} />
          <Readout label="Unknown" value={String(data.counts.unknown ?? 0)} />
          <Readout label="Cache TTL" value={`${data.cache_ttl_seconds}s`} />
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Discovery is a free, read-only catalogue call. Refreshing it never runs
          inference, never warms a backend and never consumes quota.
        </p>
      </AdminSection>

      <AdminSection
        title="Models"
        subtitle="Approving keeps an available override row; revoking removes it and the model returns to pending. Disabling suspends an approved model without losing the approval."
        actions={<ManagedByRevora size="xs" />}
      >
        <FilterBar label="Catalogue filters">
          <SelectFilter
            value={scope}
            aria-label="Catalogue scope"
            onChange={(event) => setScope(event.target.value === 'all' ? 'all' : 'chat')}
          >
            <option value="chat">Canonical chat models</option>
            <option value="all">All advertised identifiers</option>
          </SelectFilter>
        </FilterBar>
        {visible.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            No models match this view. Refresh the catalogue or widen the scope.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[880px] text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Model</th>
                  <th className="py-2 pr-4 font-medium">Kind</th>
                  <th className="py-2 pr-4 font-medium">Context</th>
                  <th className="py-2 pr-4 font-medium">Approval</th>
                  <th className="py-2 pr-4 font-medium">Chat</th>
                  <th className="py-2 pr-4 font-medium">Reviews</th>
                  <th className="py-2 pr-4 font-medium">State</th>
                  <th className="py-2 pr-4 font-medium">Readiness</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((model) => {
                  const identity = {
                    key: model.key,
                    display_name: model.display_name,
                    provider: CLOUD_PROVIDER,
                    category: CLOUD_PROVIDER,
                  };
                  const approvable = model.classification === 'chat';
                  const busy = pendingModelId === model.model_id;
                  return (
                    <tr key={model.model_id} className="border-b border-border/60 last:border-0">
                      <td className="py-2.5 pr-4">
                        <span className="flex min-w-0 items-center gap-2 font-medium text-foreground">
                          <ModelIcon model={identity} size={16} className="shrink-0" />
                          <span className="min-w-0">
                            <span className="block truncate" title={model.model_id}>
                              {model.display_name}
                            </span>
                            <span className="block truncate text-xs font-normal text-muted-foreground">
                              {model.canonical && model.canonical !== model.model_id
                                ? `${model.model_id} → ${model.canonical}`
                                : model.model_id}
                            </span>
                          </span>
                        </span>
                      </td>
                      <td className="py-2.5 pr-4">
                        <Pill tone={CLASSIFICATION_TONE[model.classification] ?? 'muted'}>
                          {model.classification}
                        </Pill>
                      </td>
                      <td className="py-2.5 pr-4 tabular-nums text-muted-foreground">
                        {model.context_window
                          ? `${Math.round(model.context_window / 1024)}K`
                          : '—'}
                      </td>
                      <td className="py-2.5 pr-4">
                        {approvable ? (
                          <ToggleButton
                            active={model.approved}
                            label={model.approved ? 'Revoke' : 'Approve'}
                            disabled={busy}
                            onClick={() => approve(model, !model.approved)}
                            title={
                              model.approved
                                ? 'Revoke the approval; the model returns to pending'
                                : 'Approve this model for its enabled surfaces'
                            }
                          />
                        ) : (
                          <Pill tone="muted">Not approvable</Pill>
                        )}
                      </td>
                      <td className="py-2.5 pr-4">
                        <ToggleButton
                          active={model.chat_enabled}
                          label={model.chat_enabled ? 'On' : 'Off'}
                          disabled={busy || !model.approved}
                          onClick={() =>
                            update.mutate({
                              modelId: model.model_id,
                              patch: { chat_enabled: !model.chat_enabled },
                            })
                          }
                          title={
                            model.approved
                              ? 'Toggle Chat availability for this model'
                              : 'Approve the model before enabling Chat'
                          }
                        />
                      </td>
                      <td className="py-2.5 pr-4">
                        <ToggleButton
                          active={model.review_enabled}
                          label={model.review_enabled ? 'On' : 'Off'}
                          disabled={busy || !model.approved}
                          onClick={() =>
                            update.mutate({
                              modelId: model.model_id,
                              patch: { review_enabled: !model.review_enabled },
                            })
                          }
                          title={
                            model.approved
                              ? 'Toggle Review availability for this model'
                              : 'Approve the model before enabling Reviews'
                          }
                        />
                      </td>
                      <td className="py-2.5 pr-4">
                        <ToggleButton
                          active={!model.disabled}
                          label={model.disabled ? 'Disabled' : 'Enabled'}
                          disabled={busy || !model.approved}
                          onClick={() =>
                            update.mutate({
                              modelId: model.model_id,
                              patch: { disabled: !model.disabled },
                            })
                          }
                          title={
                            model.approved
                              ? 'Suspend or resume this model without revoking it'
                              : 'Approve the model before suspending it'
                          }
                        />
                      </td>
                      <td className="py-2.5 pr-4">
                        <Pill tone={model.ready ? 'success' : 'muted'} dot>
                          {model.ready ? 'Ready' : REASON_TEXT[model.reason_code] ?? 'Unavailable'}
                        </Pill>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </AdminSection>

      <ConfirmDialog
        open={revokeTarget !== null}
        title={revokeTarget ? `Revoke ${revokeTarget.display_name}?` : 'Revoke approval?'}
        description="The model returns to pending: it disappears from user Chat and Review availability until an administrator approves it again. Chat and Review toggles are removed with the approval."
        confirmLabel="Revoke approval"
        tone="danger"
        busy={update.isPending}
        onCancel={() => setRevokeTarget(null)}
        onConfirm={() => {
          if (!revokeTarget) return;
          update.mutate(
            { modelId: revokeTarget.model_id, patch: { approved: false } },
            { onSettled: () => setRevokeTarget(null) },
          );
        }}
      />
    </AdminPage>
  );
}