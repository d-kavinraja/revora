'use client';

import { useMemo, useState } from 'react';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Boxes, RotateCcw } from 'lucide-react';
import {
  adminApi,
  type AdminModelOverride,
  type AdminModelOverrideUpdate,
  type AdminProviderRead,
} from '@/lib/api';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { Pill } from '@/components/shared/pill';
import { TextFilter } from '@/components/shared/text-filter';
import { ProviderBadge } from '@/components/ui/provider-brand';
import { useToast } from '@/components/ui/toaster';
import { AdminPage, AdminSection } from '@/components/admin/page-shell';
import {
  AdminButton,
  ADMIN_INPUT_CLASS,
  Field,
} from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

const EMPTY_OVERRIDES: AdminModelOverride[] = [];
const EMPTY_PROVIDERS: AdminProviderRead[] = [];

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
  const [overrideSearch, setOverrideSearch] = useState('');

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

  const providers = providersQuery.data?.items ?? EMPTY_PROVIDERS;
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
  const overrides = overridesQuery.data ?? EMPTY_OVERRIDES;
  const filteredOverrides = useMemo(() => {
    const query = overrideSearch.trim().toLowerCase();
    if (!query) return overrides;
    return overrides.filter((override) => {
      const provider = (
        providers.find((item) => item.slug === override.provider_slug)
          ?.display_name ?? override.provider_slug
      ).toLowerCase();
      return (
        override.model_id.toLowerCase().includes(query) ||
        override.provider_slug.toLowerCase().includes(query) ||
        provider.includes(query)
      );
    });
  }, [overrides, overrideSearch, providers]);

  return (
    <AdminPage
      eyebrow="System"
      title="Models"
      description="Per-model overrides. Disabling a model hides it from user lists, skips it in routing and refuses explicit execution. The provider and its other models stay untouched."
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
        <AdminSection
          title="Disable a model"
          subtitle="Pick the provider and enter the exact model identifier used in user model lists."
        >
          <div className="space-y-3">
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
        </AdminSection>

        <AdminSection
          title="Active overrides"
          subtitle={
            overrides.length === 0
              ? 'No models are currently disabled.'
              : `${filteredOverrides.length} of ${overrides.length} disabled model${
                  overrides.length === 1 ? '' : 's'
                }`
          }
          actions={
            overrides.length > 1 ? (
              <TextFilter
                value={overrideSearch}
                onChange={setOverrideSearch}
                placeholder="Search overrides…"
                ariaLabel="Search model overrides"
                className="w-full sm:w-56"
              />
            ) : undefined
          }
        >
          {overrides.length === 0 ? (
            <div className="flex items-center gap-3 rounded-lg border border-dashed border-border bg-surface-2/50 p-4">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-1">
                <Boxes size={17} aria-hidden="true" />
              </span>
              <p className="text-sm text-muted-foreground">
                All registered models are available to users.
              </p>
            </div>
          ) : filteredOverrides.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border bg-surface-2/50 p-4 text-sm text-muted-foreground">
              No overrides match “{overrideSearch.trim()}”.
            </p>
          ) : (
            <div className="space-y-3">
              {filteredOverrides.map((override) => {
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
                        <ProviderBadge
                          slug={override.provider_slug}
                          label={providerName(override.provider_slug)}
                          size="sm"
                          muted
                          className="mt-1 max-w-56"
                        />
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
        </AdminSection>
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
