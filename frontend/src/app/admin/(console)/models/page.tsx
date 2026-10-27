'use client';

import { useState } from 'react';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Boxes, RotateCcw } from 'lucide-react';
import { adminApi, type AdminModelOverrideUpdate } from '@/lib/api';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { Pill } from '@/components/shared/pill';
import { useToast } from '@/components/ui/toaster';

function errorDetail(error: unknown): string | null {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  return null;
}

const fieldLabelCls =
  'block text-xs font-medium text-muted-foreground mb-1';
const fieldCls =
  'w-full h-11 rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';

export default function AdminModelsPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [providerSlug, setProviderSlug] = useState('');
  const [modelId, setModelId] = useState('');
  const [message, setMessage] = useState('');
  const [confirmingDisable, setConfirmingDisable] = useState(false);
  const [restoringKey, setRestoringKey] = useState<string | null>(null);

  const overridesQuery = useQuery({
    queryKey: ['admin', 'model-overrides'],
    queryFn: adminApi.modelOverrides,
    retry: 1,
  });

  const providersQuery = useQuery({
    queryKey: ['admin', 'providers'],
    queryFn: adminApi.providers,
    retry: 1,
  });

  const providers = providersQuery.data?.items ?? [];
  const providerName = (slug: string) =>
    providers.find((provider) => provider.slug === slug)?.display_name ?? slug;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['admin', 'model-overrides'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-features'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
  };

  const applyMutation = useMutation({
    mutationFn: (input: AdminModelOverrideUpdate) =>
      adminApi.updateModelOverride(input),
    onSuccess: (override, input) => {
      toast({
        title:
          input.status === 'disabled'
            ? 'Model disabled'
            : 'Model restored',
        description:
          input.status === 'disabled'
            ? `${override.model_id} no longer appears in user model lists and is refused on execution. Other models and the provider are unaffected.`
            : `${override.model_id} is available to users again.`,
        type: 'success',
      });
      setConfirmingDisable(false);
      setRestoringKey(null);
      if (input.status === 'disabled') {
        setModelId('');
        setMessage('');
      }
      invalidate();
    },
    onError: (error) => {
      toast({
        title:
          restoringKey !== null
            ? 'Could not restore model'
            : 'Could not disable model',
        description: errorDetail(error) ?? undefined,
        type: 'error',
      });
      setConfirmingDisable(false);
      setRestoringKey(null);
    },
  });

  const loadError = overridesQuery.isError || providersQuery.isError;
  const overrides = overridesQuery.data ?? [];

  return (
    <div>
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
          Models
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Per-model overrides. A disabled model disappears from user-facing
          model lists, is skipped by the router and is refused on explicit
          execution — the provider and its other models are untouched.
          Setting a model back to available clears the override immediately,
          with no user action needed. All changes are audited.
        </p>
      </div>

      {loadError && (
        <div
          role="alert"
          className="mt-4 flex items-center gap-3 rounded-xl border border-error/40 bg-error/10 p-4 text-sm text-error"
        >
          <AlertTriangle size={18} className="shrink-0" />
          <span>
            Could not load model overrides.{' '}
            <button
              type="button"
              onClick={() => {
                void overridesQuery.refetch();
                void providersQuery.refetch();
              }}
              className="underline underline-offset-2 cursor-pointer"
            >
              Try again
            </button>
          </span>
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface-1 p-5">
          <p className="text-sm font-semibold text-foreground">Disable a model</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Pick the provider and type the exact model identifier (as it
            appears in user model lists, e.g. a registry model id).
          </p>

          <div className="mt-4 space-y-3">
            <div>
              <label htmlFor="override-provider" className={fieldLabelCls}>
                Provider
              </label>
              <select
                id="override-provider"
                value={providerSlug}
                onChange={(event) => setProviderSlug(event.target.value)}
                className={`${fieldCls} cursor-pointer`}
              >
                <option value="">Select a provider…</option>
                {providers.map((provider) => (
                  <option key={provider.slug} value={provider.slug}>
                    {provider.display_name} ({provider.slug})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="override-model" className={fieldLabelCls}>
                Model ID
              </label>
              <input
                id="override-model"
                type="text"
                value={modelId}
                maxLength={200}
                placeholder="e.g. gemini-2.5-flash"
                onChange={(event) => setModelId(event.target.value)}
                className={fieldCls}
              />
            </div>
            <div>
              <label htmlFor="override-message" className={fieldLabelCls}>
                User-facing message (optional)
              </label>
              <input
                id="override-message"
                type="text"
                value={message}
                maxLength={300}
                placeholder="Shown when this model is referenced (defaults to the standard unavailable message)."
                onChange={(event) => setMessage(event.target.value)}
                className={fieldCls}
              />
            </div>
            <button
              type="button"
              disabled={
                !providerSlug ||
                !modelId.trim() ||
                applyMutation.isPending
              }
              onClick={() => setConfirmingDisable(true)}
              className="inline-flex h-11 items-center gap-2 rounded-lg border border-error/30 bg-error/10 px-4 text-sm font-medium text-error transition-colors hover:bg-error/20 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            >
              Disable model
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-surface-1 p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-surface-2">
                <Boxes size={17} />
              </span>
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Active overrides
                </p>
                <p className="text-xs text-muted-foreground">
                  {overrides.length === 0
                    ? 'No models are currently disabled.'
                    : `${overrides.length} disabled model${overrides.length === 1 ? '' : 's'}`}
                </p>
              </div>
            </div>
          </div>

          {overrides.length > 0 && (
            <div className="mt-4 space-y-3">
              {overrides.map((override) => {
                const key = `${override.provider_slug}:${override.model_id}`;
                const busy =
                  applyMutation.isPending && restoringKey === key;
                return (
                  <div
                    key={key}
                    className="rounded-lg border border-border bg-surface-2 p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-foreground truncate">
                          {override.model_id}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {providerName(override.provider_slug)} ·{' '}
                          <span className="font-mono">
                            {override.provider_slug}
                          </span>
                        </p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Pill tone="error">Disabled</Pill>
                        <button
                          type="button"
                          disabled={applyMutation.isPending}
                          onClick={() => {
                            setRestoringKey(key);
                            applyMutation.mutate({
                              provider_slug: override.provider_slug,
                              model_id: override.model_id,
                              status: 'available',
                              message: null,
                            });
                          }}
                          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border bg-surface-1 px-3 text-xs font-medium text-foreground transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                        >
                          <RotateCcw size={13} />
                          {busy ? 'Restoring…' : 'Restore'}
                        </button>
                      </div>
                    </div>
                    {override.message && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        Message: {override.message}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmingDisable}
        title="Disable model"
        description={`${modelId.trim()} will disappear from user-facing model lists, be skipped by routing and be refused with a 400 on explicit execution. The provider itself is not affected.`}
        tone="danger"
        confirmLabel="Disable"
        busy={applyMutation.isPending}
        onConfirm={() => {
          applyMutation.mutate({
            provider_slug: providerSlug,
            model_id: modelId.trim(),
            status: 'disabled',
            message: message.trim() || null,
          });
        }}
        onCancel={() => {
          if (!applyMutation.isPending) setConfirmingDisable(false);
        }}
      >
        <p className="text-sm text-muted-foreground">
          The change is applied immediately and written to the audit log.
          Restore the model at any time from “Active overrides”.
        </p>
      </ConfirmDialog>
    </div>
  );
}
