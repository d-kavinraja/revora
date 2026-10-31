'use client';

import { useState } from 'react';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Boxes, RotateCcw } from 'lucide-react';
import { adminApi, type AdminModelOverrideUpdate } from '@/lib/api';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { Pill } from '@/components/shared/pill';
import { useToast } from '@/components/ui/toaster';
import { AdminPage } from '@/components/admin/page-shell';
import {
  AdminButton,
  ADMIN_INPUT_CLASS,
  Field,
} from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

function errorDetail(error: unknown): string | null {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  return null;
}

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
    <AdminPage
      eyebrow="System"
      title="Models"
      description="Per-model overrides. A disabled model disappears from user-facing model lists, is skipped by the router and is refused on explicit execution — the provider and its other models are untouched. Setting a model back to available clears the override immediately, with no user action needed. All changes are audited."
    >
      {loadError && (
        <QueryError
          message="Could not load model overrides."
          onRetry={() => {
            void overridesQuery.refetch();
            void providersQuery.refetch();
          }}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="min-w-0 rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-sm font-semibold text-foreground">Disable a model</h2>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            Pick the provider and type the exact model identifier (as it
            appears in user model lists, e.g. a registry model id).
          </p>

          <div className="mt-4 space-y-3">
            <Field label="Provider" htmlFor="override-provider">
              <select
                id="override-provider"
                value={providerSlug}
                onChange={(event) => setProviderSlug(event.target.value)}
                className={`${ADMIN_INPUT_CLASS} cursor-pointer`}
              >
                <option value="">Select a provider…</option>
                {providers.map((provider) => (
                  <option key={provider.slug} value={provider.slug}>
                    {provider.display_name} ({provider.slug})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Model ID" htmlFor="override-model">
              <input
                id="override-model"
                type="text"
                value={modelId}
                maxLength={200}
                placeholder="e.g. gemini-2.5-flash"
                onChange={(event) => setModelId(event.target.value)}
                className={ADMIN_INPUT_CLASS}
              />
            </Field>
            <Field label="User-facing message (optional)" htmlFor="override-message">
              <input
                id="override-message"
                type="text"
                value={message}
                maxLength={300}
                placeholder="Shown when this model is referenced (defaults to the standard unavailable message)."
                onChange={(event) => setMessage(event.target.value)}
                className={ADMIN_INPUT_CLASS}
              />
            </Field>
            <AdminButton
              variant="dangerSoft"
              disabled={!providerSlug || !modelId.trim() || applyMutation.isPending}
              onClick={() => setConfirmingDisable(true)}
            >
              Disable model
            </AdminButton>
          </div>
        </section>

        <section className="min-w-0 rounded-xl border border-border bg-surface-1 p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2">
                <Boxes size={17} aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-foreground">
                  Active overrides
                </h2>
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
                        <p className="truncate text-sm font-medium text-foreground">
                          {override.model_id}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {providerName(override.provider_slug)} ·{' '}
                          <span className="font-mono">
                            {override.provider_slug}
                          </span>
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Pill tone="error" dot>
                          Disabled
                        </Pill>
                        <AdminButton
                          size="sm"
                          variant="secondary"
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
                        >
                          <RotateCcw size={13} />
                          {busy ? 'Restoring…' : 'Restore'}
                        </AdminButton>
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
        </section>
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
    </AdminPage>
  );
}
