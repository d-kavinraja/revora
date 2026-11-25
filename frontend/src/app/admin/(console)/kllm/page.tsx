'use client';

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  PinIcon,
  PlayIcon,
  RefreshCwIcon,
  RotateCwIcon,
  SquareIcon,
} from 'lucide-react';
import {
  adminApi,
  type KllmAutoloadPolicy,
  type KllmModel,
} from '@/lib/api';
import { apiErrorMessage, isApiTransportError } from '@/lib/api-transport';
import { AdminPage } from '@/components/admin/page-shell';
import { StatusRibbon } from '@/components/admin/metrics';
import {
  AdminButton,
  AdminSwitch,
  ADMIN_INPUT_CLASS,
  CheckboxRow,
  Field,
} from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { Pill, type PillTone } from '@/components/shared/pill';
import { ModelIcon } from '@/components/ui/model-icon';
import { ProviderIcon } from '@/components/ui/provider-icon';
import { useToast } from '@/components/ui/toaster';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { KLLM_MANAGEMENT_LABEL, KLLM_PROVIDER, modelDisplayName } from '@/lib/chat-state';

const REFRESH_INTERVAL_MS = 15_000;

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

const BACKEND_TONE: Record<string, PillTone> = {
  running: 'success',
  draining: 'warning',
  retiring: 'warning',
  unhealthy: 'error',
};

type PendingAction =
  | { kind: 'load'; model: string }
  | {
      kind: 'unload';
      model: string;
      sessions: number;
      inflight: number;
      disableAlwaysOn: boolean;
    }
  | { kind: 'clear_block'; model: string }
  | { kind: 'stop'; id: string; model: string | null; sessions: number; inflight: number }
  | { kind: 'rotate'; id: string; model: string | null }
  | { kind: 'keep'; size: number };

// Shared helper keeps HTTP details and transport failures distinct, so a
// backend that was never reached is never shown as a policy validation error.
function errorMessage(err: unknown): string {
  return apiErrorMessage(err);
}

/**
 * Admin-only kLLM lifecycle console.
 *
 * Every call goes to the isolated `/api/v1/admin/kllm/*` namespace, which
 * requires the admin session cookie. The ordinary user namespace has no
 * lifecycle mutations at all.
 */
export default function AdminKllmPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [keepSize, setKeepSize] = useState(0);
  const [forceUnload, setForceUnload] = useState(false);
  const [forceStop, setForceStop] = useState(false);

  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['admin', 'kllm'],
    queryFn: () => adminApi.kllm({ refresh: true }),
    refetchInterval: REFRESH_INTERVAL_MS,
    retry: false,
  });

  const policy = data?.autoload;

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['admin', 'kllm'] });
  };

  const action = useMutation({
    mutationFn: async (next: PendingAction) => {
      switch (next.kind) {
        case 'load':
          return adminApi.loadKllmModel(next.model, true);
        case 'unload':
          return adminApi.unloadKllmModel(
            next.model,
            true,
            forceUnload,
            next.disableAlwaysOn,
          );
        case 'clear_block':
          return adminApi.allowKllmAutoload(next.model, true);
        case 'stop':
          return adminApi.stopKllmBackend(next.id, true, forceStop);
        case 'rotate':
          return adminApi.rotateKllmBackend(next.id, true);
        case 'keep':
          return adminApi.setKllmKeep(next.size, next.size > 0);
        default:
          throw new Error('Unsupported action');
      }
    },
    onSuccess: async (_result, next) => {
      const messages: Record<PendingAction['kind'], string> = {
        load: 'Load requested',
        unload: 'Unload requested',
        clear_block: 'Automatic loading re-enabled',
        stop: 'Stop requested',
        rotate: 'Rotation requested',
        keep: 'Desired pool updated',
      };
      toast({ title: messages[next.kind], type: 'success' });
      setPending(null);
      setForceUnload(false);
      setForceStop(false);
      await invalidate();
    },
    onError: (err) => {
      toast({
        title: 'Action failed',
        description: errorMessage(err),
        type: 'error',
      });
    },
  });

  const savePolicy = useMutation({
    mutationFn: (next: KllmAutoloadPolicy) => adminApi.updateKllmAutoload(next),
    onSuccess: async () => {
      toast({ title: 'Automatic loading policy saved', type: 'success' });
      try {
        await invalidate();
      } catch {
        // A refresh failure is reported by the query's own error state. A
        // persisted policy must never be shown as a failed update because
        // the follow-up read failed.
      }
    },
    onError: (err) => {
      toast({
        title: isApiTransportError(err)
          ? 'Cannot reach the backend'
          : 'Policy update failed',
        description: errorMessage(err),
        type: 'error',
      });
    },
  });

  const models = useMemo(() => data?.models ?? [], [data?.models]);
  const backends = useMemo(() => data?.backends ?? [], [data?.backends]);
  const blockedModels = useMemo(
    () => new Set((data?.manual_unload_blocks ?? []).map((block) => block.model)),
    [data?.manual_unload_blocks],
  );
  const alwaysOnConflict =
    pending?.kind === 'unload' &&
    data?.default_model === pending.model &&
    (!data?.always_on_verified || (data?.always_on_size ?? 0) > 0);

  const modelUsage = useMemo(() => {
    const usage = new Map<string, { sessions: number; inflight: number }>();
    for (const backend of backends) {
      if (!backend.model) continue;
      const current = usage.get(backend.model) ?? { sessions: 0, inflight: 0 };
      current.sessions += backend.sessions ?? 0;
      current.inflight += backend.inflight ?? 0;
      usage.set(backend.model, current);
    }
    return usage;
  }, [backends]);

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
        title="kLLM"
        description="Model lifecycle controls for the managed local inference provider."
      >
        <QueryError
          message={errorMessage(error)}
          onRetry={() => void refetch()}
        />
      </AdminPage>
    );
  }

  return (
    <AdminPage
      eyebrow="System"
      icon={<ProviderIcon slug="kllm" size={28} />}
      title="kLLM lifecycle"
      description="Load and unload managed models, control backends and configure the automatic-loading policy. kLLM owns serving; Revora never substitutes a model."
      actions={
        <AdminButton
          onClick={() => void refetch()}
          disabled={isFetching}
          variant="secondary"
          size="sm"
        >
          {isFetching ? (
            <LoaderIcon size={14} className="animate-spin" />
          ) : (
            <RefreshCwIcon size={14} />
          )}
          Refresh
        </AdminButton>
      }
    >
      <StatusRibbon
        label="Runtime state"
        verdict={
          !data.enabled
            ? 'Disabled'
            : data.stale
              ? 'Stale'
              : data.reachable
                ? 'Live'
                : 'Unreachable'
        }
        hint={
          data.always_on_verified
            ? `Always-on pool verified at ${data.always_on_size} models.`
            : 'Always-on pool size is not verified.'
        }
        readouts={[
          {
            key: 'models',
            label: 'Ready models',
            value: String(data.summary.ready_models),
            sub: `${data.summary.loading_models} loading`,
          },
          {
            key: 'backends',
            label: 'Backends',
            value: String(data.summary.backends),
            sub: `${data.summary.sessions} sessions`,
          },
          {
            key: 'sessions',
            label: 'Active Revora sessions',
            value: String(data.active_sessions),
          },
          {
            key: 'always-on',
            label: 'Always-on size',
            value: data.always_on_verified
              ? String(data.always_on_size)
              : 'Unknown',
            sub: data.always_on_verified ? undefined : 'Not verified',
          },
        ]}
      />
      <div className="space-y-8">
        <section aria-labelledby="kllm-models-heading">
          <div className="flex items-center justify-between gap-3">
            <h2 id="kllm-models-heading" className="text-lg font-semibold text-foreground">
              Models
            </h2>
            <Pill tone="brand">{KLLM_MANAGEMENT_LABEL}</Pill>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Unloading stops every backend and pending launch serving that exact
            model. kLLM offers no drain guarantee, so a model with active
            sessions refuses to unload unless you force it.
          </p>
          <div className="mt-3 overflow-x-auto rounded-xl border border-border bg-surface-1">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-surface-2/60 text-left text-xs font-medium text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Model</th>
                  <th className="px-4 py-2.5 font-medium">Readiness</th>
                  <th className="px-4 py-2.5 font-medium">Backends</th>
                  <th className="px-4 py-2.5 font-medium">In use</th>
                  <th className="px-4 py-2.5 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {models.map((model: KllmModel) => {
                  const usage = modelUsage.get(model.key);
                  const sessions = usage?.sessions ?? 0;
                  const inflight = usage?.inflight ?? 0;
                  return (
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
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Pill
                            tone={READINESS_TONE[model.readiness] ?? 'muted'}
                            dot
                          >
                            {READINESS_LABEL[model.readiness] ?? model.readiness}
                          </Pill>
                          {blockedModels.has(model.key) && (
                            <Pill tone="warning">Auto-load blocked</Pill>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {model.backend_count}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {sessions || inflight
                          ? `${sessions} sessions, ${inflight} in flight`
                          : '—'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          {blockedModels.has(model.key) && (
                            <AdminButton
                              size="sm"
                              variant="secondary"
                              disabled={action.isPending}
                              onClick={() =>
                                setPending({ kind: 'clear_block', model: model.key })
                              }
                            >
                              Allow auto-load
                            </AdminButton>
                          )}
                          {!model.ready &&
                            model.status !== 'loading' &&
                            model.status !== 'failed' && (
                            <AdminButton
                              size="sm"
                              variant="primary"
                              disabled={action.isPending}
                              onClick={() =>
                                setPending({ kind: 'load', model: model.key })
                              }
                            >
                              <PlayIcon size={13} /> Load
                            </AdminButton>
                          )}
                          {model.status !== 'unloaded' && (
                            <AdminButton
                              size="sm"
                              variant="dangerSoft"
                              disabled={action.isPending}
                              onClick={() =>
                                setPending({
                                  kind: 'unload',
                                  model: model.key,
                                  sessions,
                                  inflight,
                                  disableAlwaysOn: false,
                                })
                              }
                            >
                              <SquareIcon size={13} /> Unload
                            </AdminButton>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {models.length === 0 && (
                  <tr>
                    <td
                      colSpan={5}
                      className="px-4 py-8 text-center text-sm text-muted-foreground"
                    >
                      kLLM did not report any models.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section aria-labelledby="kllm-backends-heading">
          <h2 id="kllm-backends-heading" className="text-lg font-semibold text-foreground">
            Backends
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Backend identities are opaque. Stopping a backend also stops every
            model and in-flight request it serves.
          </p>
          <div className="mt-3 space-y-3">
            {backends.map((backend) => (
              <div
                key={backend.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface-1 p-4"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill tone={BACKEND_TONE[backend.state] ?? 'muted'} dot>
                      {backend.state}
                    </Pill>
                    <span className="truncate text-sm font-medium text-foreground">
                      {backend.model ?? 'Unknown model'}
                    </span>
                    {backend.pinned && (
                      <Pill tone="brand">
                        <PinIcon size={11} /> Pinned
                      </Pill>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {backend.sessions ?? 0} sessions, {backend.inflight ?? 0} in
                    flight
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <AdminButton
                    size="sm"
                    variant="secondary"
                    disabled={action.isPending}
                    onClick={() =>
                      void adminApi
                        .pinKllmBackend(backend.id, !backend.pinned)
                        .then(async () => {
                          toast({
                            title: backend.pinned
                              ? 'Backend unpinned'
                              : 'Backend pinned',
                            type: 'success',
                          });
                          await invalidate();
                        })
                        .catch((err) =>
                          toast({
                            title: 'Action failed',
                            description: errorMessage(err),
                            type: 'error',
                          }),
                        )
                    }
                  >
                    <PinIcon size={13} /> {backend.pinned ? 'Unpin' : 'Pin'}
                  </AdminButton>
                  <AdminButton
                    size="sm"
                    variant="secondary"
                    disabled={action.isPending}
                    onClick={() =>
                      setPending({
                        kind: 'rotate',
                        id: backend.id,
                        model: backend.model,
                      })
                    }
                  >
                    <RotateCwIcon size={13} /> Rotate
                  </AdminButton>
                  <AdminButton
                    size="sm"
                    variant="dangerSoft"
                    disabled={action.isPending}
                    onClick={() =>
                      setPending({
                        kind: 'stop',
                        id: backend.id,
                        model: backend.model,
                        sessions: backend.sessions ?? 0,
                        inflight: backend.inflight ?? 0,
                      })
                    }
                  >
                    <SquareIcon size={13} /> Stop
                  </AdminButton>
                </div>
              </div>
            ))}
            {backends.length === 0 && (
              <p className="rounded-xl border border-border bg-surface-1 p-6 text-center text-sm text-muted-foreground">
                No backends are running.
              </p>
            )}
          </div>
        </section>

        <section aria-labelledby="kllm-keep-heading">
          <h2 id="kllm-keep-heading" className="text-lg font-semibold text-foreground">
            Always-on pool
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Revora controls kLLM&apos;s desired pool only. kLLM also enforces its
            own <code>autoscale.min_backends</code>, which must be zero to fully
            disable the always-on default model.
          </p>
          {!data.always_on_verified && (
            <p className="mt-1 text-xs text-warning">
              kLLM&apos;s effective always-on setting could not be verified.
            </p>
          )}
          {data.always_on_verified && (
            <p className="mt-1 text-xs text-muted-foreground">
              Effective minimum {data.always_on_size}, desired pool{' '}
              {data.always_on_desired_pool}, kLLM min_backends{' '}
              {data.always_on_min_backends}
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface-1 p-4">
            <Field label="Pool size" htmlFor="kllm-keep-size" className="w-40">
              <input
                key={`always-on-${data?.always_on_size ?? 0}`}
                id="kllm-keep-size"
                type="number"
                min={0}
                max={10}
                defaultValue={data?.always_on_size ?? 0}
                onChange={(event) =>
                  setKeepSize(
                    Math.max(0, Math.min(10, Number(event.target.value) || 0)),
                  )
                }
                className={ADMIN_INPUT_CLASS}
              />
            </Field>
            <AdminButton
              variant="primary"
              disabled={action.isPending}
              onClick={() => setPending({ kind: 'keep', size: keepSize })}
            >
              Apply
            </AdminButton>
            <span className="text-xs text-muted-foreground">
              0 sets the desired pool to zero; kLLM min_backends must also be 0.
            </span>
          </div>
        </section>

        <PolicyEditor
          key={`${policy?.version ?? 0}:${policy?.changed_at ?? 'initial'}`}
          policy={policy}
          models={models}
          busy={savePolicy.isPending}
          onSave={(next) => savePolicy.mutate(next)}
        />
      </div>

      <ConfirmDialog
        open={pending?.kind === 'load'}
        title={pending?.kind === 'load' ? `Load ${pending.model}?` : 'Load model?'}
        description="kLLM will start a new backend for this model. It can take several minutes before it becomes ready and may consume GPU quota on the kLLM host."
        confirmLabel="Load model"
        busy={action.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && action.mutate(pending)}
      />

      <ConfirmDialog
        open={pending?.kind === 'unload'}
        title={pending?.kind === 'unload' ? `Unload ${pending.model}?` : 'Unload model?'}
        description={
          alwaysOnConflict
            ? !data?.always_on_verified
              ? "kLLM's effective always-on setting could not be verified. Revora can only change the desired pool; set autoscale.min_backends to 0 in kLLM before unloading this default model."
              : `kLLM's effective always-on minimum is ${data?.always_on_size} backend(s). Revora can set the desired pool to zero, but autoscale.min_backends (${data?.always_on_min_backends}) must also be 0 in kLLM.`
            : pending?.kind === 'unload' && (pending.sessions > 0 || pending.inflight > 0)
              ? `This model is serving ${pending.sessions} session(s) and ${pending.inflight} in-flight request(s). kLLM provides no drain guarantee, so these requests are interrupted.`
              : 'This stops every backend and pending launch serving this exact model. Automatic loading stays blocked until you explicitly allow it again.'
        }
        confirmLabel="Unload model"
        tone="danger"
        busy={action.isPending}
        onCancel={() => {
          setPending(null);
          setForceUnload(false);
        }}
        onConfirm={() => pending && action.mutate(pending)}
      >
        {pending?.kind === 'unload' && alwaysOnConflict && (
          <label className="flex min-h-11 items-start gap-3">
            <input
              type="checkbox"
              checked={pending.disableAlwaysOn}
              onChange={(event) =>
                setPending({
                  ...pending,
                  disableAlwaysOn: event.target.checked,
                })
              }
              className="mt-0.5 h-4 w-4 shrink-0 rounded border-border accent-brand"
            />
            <span className="text-sm text-foreground">
              Set kLLM&apos;s desired pool to zero before unloading this default model
            </span>
          </label>
        )}
        {pending?.kind === 'unload' &&
          (pending.sessions > 0 || pending.inflight > 0) && (
            <label className="flex min-h-11 items-start gap-3">
              <input
                type="checkbox"
                checked={forceUnload}
                onChange={(event) => setForceUnload(event.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 rounded border-border accent-brand"
              />
              <span className="text-sm text-foreground">
                Force unload despite active sessions (interrupts in-flight work)
              </span>
            </label>
          )}
      </ConfirmDialog>

      <ConfirmDialog
        open={pending?.kind === 'clear_block'}
        title={
          pending?.kind === 'clear_block'
            ? `Allow automatic loading of ${pending.model}?`
            : 'Allow automatic loading?'
        }
        description="Revora will no longer treat the earlier administrator unload as a permanent block. The model may load again on a future review, login, or active Revora session."
        confirmLabel="Allow automatic loading"
        busy={action.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && action.mutate(pending)}
      />

      <ConfirmDialog
        open={pending?.kind === 'stop'}
        title="Stop this backend?"
        description={
          pending?.kind === 'stop'
            ? `This stops every model and in-flight request served by this backend${
                pending.model ? ` (${pending.model})` : ''
              }. It cannot be undone from Revora.`
            : 'This stops the backend.'
        }
        confirmLabel="Stop backend"
        tone="danger"
        busy={action.isPending}
        onCancel={() => {
          setPending(null);
          setForceStop(false);
        }}
        onConfirm={() => pending && action.mutate(pending)}
      >
        {pending?.kind === 'stop' &&
          (pending.sessions > 0 || pending.inflight > 0) && (
            <label className="flex min-h-11 items-start gap-3">
              <input
                type="checkbox"
                checked={forceStop}
                onChange={(event) => setForceStop(event.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 rounded border-border accent-brand"
              />
              <span className="text-sm text-foreground">
                Force stop despite active sessions (interrupts in-flight work)
              </span>
            </label>
          )}
      </ConfirmDialog>

      <ConfirmDialog
        open={pending?.kind === 'rotate'}
        title="Rotate this backend?"
        description={`kLLM will start a fresh backend${
          pending?.kind === 'rotate' && pending.model
            ? ` for ${pending.model}`
            : ''
        }, hand sessions over, then stop the old one. Capacity is briefly reduced during the hand-off.`}
        confirmLabel="Rotate backend"
        busy={action.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && action.mutate(pending)}
      />

      <ConfirmDialog
        open={pending?.kind === 'keep'}
        title={
          pending?.kind === 'keep' && pending.size > 0
            ? `Keep ${pending.size} model(s) always on?`
            : 'Disable the always-on pool?'
        }
        description={
          pending?.kind === 'keep' && pending.size === 0
            ? "Revora will set kLLM's desired pool to zero. kLLM's own autoscale.min_backends must also be 0 for always-on to be fully disabled."
            : "kLLM will maintain this many backends around the clock and auto-rotate them before the session cap. This consumes GPU quota continuously."
        }
        confirmLabel={pending?.kind === 'keep' && pending.size > 0 ? 'Enable always-on' : 'Set desired pool to zero'}
        busy={action.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && action.mutate(pending)}
      />
    </AdminPage>
  );
}

function PolicyEditor({
  policy,
  models,
  busy,
  onSave,
}: {
  policy: KllmAutoloadPolicy | undefined;
  models: KllmModel[];
  busy: boolean;
  onSave: (next: KllmAutoloadPolicy) => void;
}) {
  const [draft, setDraft] = useState<KllmAutoloadPolicy | null>(() =>
    policy ? {
      ...policy,
      review_autoload: {
        ...policy.review_autoload,
        allowed_models: [...policy.review_autoload.allowed_models],
      },
      login_preload: {
        ...policy.login_preload,
        allowed_models: [...policy.login_preload.allowed_models],
      },
      active_session_autoload: {
        ...policy.active_session_autoload,
        allowed_models: [...policy.active_session_autoload.allowed_models],
      },
    } : null,
  );

  if (!draft) return null;

  const toggleModel = (
    group: 'review_autoload' | 'login_preload' | 'active_session_autoload',
    model: string,
  ) => {
    setDraft((current) => {
      if (!current) return current;
      const allowed = current[group].allowed_models;
      const next = allowed.includes(model)
        ? allowed.filter((item) => item !== model)
        : [...allowed, model];
      return {
        ...current,
        [group]: { ...current[group], allowed_models: next },
      };
    });
  };

  return (
    <section aria-labelledby="kllm-autoload-heading">
      <h2 id="kllm-autoload-heading" className="text-lg font-semibold text-foreground">
        Automatic loading
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        All three policies are disabled by default. Only the exact models you
        approve here may ever be loaded automatically, and Revora never
        substitutes a different model.
      </p>

      <div className="mt-3 space-y-4 rounded-xl border border-border bg-surface-1 p-4">
        <PolicyGroup
          title="Load on review demand"
          description="When a review needs an approved model that is not loaded, Revora asks kLLM to load it and waits for genuine readiness before running the review."
          enabled={draft.review_autoload.enabled}
          onToggle={(enabled) =>
            setDraft({
              ...draft,
              review_autoload: { ...draft.review_autoload, enabled },
            })
          }
          allowed={draft.review_autoload.allowed_models}
          models={models}
          onToggleModel={(model) => toggleModel('review_autoload', model)}
        />

        <PolicyGroup
          title="Preload once on login"
          description="After a successful password or GitHub sign-in, Revora asks kLLM to load the approved models in the background. This is one-shot: login never waits for a load and never fails because of one."
          enabled={draft.login_preload.enabled}
          onToggle={(enabled) =>
            setDraft({
              ...draft,
              login_preload: { ...draft.login_preload, enabled },
            })
          }
          allowed={draft.login_preload.allowed_models}
          models={models}
          onToggleModel={(model) => toggleModel('login_preload', model)}
        />

        <PolicyGroup
          title="Keep available while a Revora session is active"
          description="When a browser tab is visible and recently active, Revora asks kLLM to reload approved models it retired for idleness. This never unloads anything; kLLM still owns idle retirement."
          enabled={draft.active_session_autoload.enabled}
          onToggle={(enabled) =>
            setDraft({
              ...draft,
              active_session_autoload: {
                ...draft.active_session_autoload,
                enabled,
              },
            })
          }
          allowed={draft.active_session_autoload.allowed_models}
          models={models}
          onToggleModel={(model) => toggleModel('active_session_autoload', model)}
        />

        <div className="grid gap-4 sm:grid-cols-3">
          <Field
            label="Load timeout (seconds)"
            htmlFor="kllm-timeout"
            hint="How long a review waits for a model to become ready."
          >
            <input
              id="kllm-timeout"
              type="number"
              min={30}
              max={3600}
              value={draft.load_timeout_seconds}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  load_timeout_seconds: Number(event.target.value) || 30,
                })
              }
              className={ADMIN_INPUT_CLASS}
            />
          </Field>
          <Field
            label="Max concurrent loads"
            htmlFor="kllm-concurrency"
            hint="Upper bound for simultaneous automatic load requests."
          >
            <input
              id="kllm-concurrency"
              type="number"
              min={1}
              max={5}
              value={draft.max_concurrent_loads}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  max_concurrent_loads: Number(event.target.value) || 1,
                })
              }
              className={ADMIN_INPUT_CLASS}
            />
          </Field>
          <Field
            label="Login preload cooldown (seconds)"
            htmlFor="kllm-cooldown"
            hint="Minimum gap between two login preload requests for the same model."
          >
            <input
              id="kllm-cooldown"
              type="number"
              min={0}
              max={86400}
              value={draft.login_preload_cooldown_seconds}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  login_preload_cooldown_seconds: Number(event.target.value) || 0,
                })
              }
              className={ADMIN_INPUT_CLASS}
            />
          </Field>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
          <p className="text-xs text-muted-foreground">
            {draft.changed_at
              ? `Last changed ${new Date(draft.changed_at).toLocaleString()}`
              : 'Never changed'}
          </p>
          <AdminButton
            variant="primary"
            disabled={busy}
            onClick={() => onSave(draft)}
          >
            {busy ? <LoaderIcon size={14} className="animate-spin" /> : null}
            Save policy
          </AdminButton>
        </div>
      </div>
    </section>
  );
}

function PolicyGroup({
  title,
  description,
  enabled,
  onToggle,
  allowed,
  models,
  onToggleModel,
}: {
  title: string;
  description: string;
  enabled: boolean;
  onToggle: (next: boolean) => void;
  allowed: string[];
  models: KllmModel[];
  onToggleModel: (model: string) => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface-2/40 p-4">
      <AdminSwitch
        checked={enabled}
        onChange={onToggle}
        title={title}
        description={description}
      />
      <div className="mt-3">
        <p className="admin-label">
          Approved models
        </p>
        {models.length === 0 ? (
          <p className="mt-1 text-xs text-muted-foreground">
            kLLM did not report a model catalogue.
          </p>
        ) : (
          <div className="mt-2 grid gap-1 sm:grid-cols-2">
            {models.map((model) => (
              <CheckboxRow
                key={model.key}
                checked={allowed.includes(model.key)}
                onChange={() => onToggleModel(model.key)}
                title={model.key}
                description={READINESS_LABEL[model.readiness] ?? model.readiness}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
