'use client';

import { useState } from 'react';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Pencil, Server } from 'lucide-react';
import {
  adminApi,
  type AdminProviderRead,
  type AdminProviderUpdate,
} from '@/lib/api';
import { DataTable, type DataTableColumn } from '@/components/shared/data-table';
import { EmptyState } from '@/components/shared/empty-state';
import { Pill, type PillTone } from '@/components/shared/pill';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { ProviderIcon } from '@/components/ui/provider-icon';
import { useToast } from '@/components/ui/toaster';
import { formatDateTime } from '@/components/shared/time-ago';

const STATUS_META: Record<string, { label: string; tone: PillTone }> = {
  available: { label: 'Available', tone: 'success' },
  under_testing: { label: 'Under testing', tone: 'warning' },
  coming_soon: { label: 'Coming soon', tone: 'info' },
  unavailable: { label: 'Temporarily unavailable', tone: 'error' },
  disabled: { label: 'Disabled', tone: 'muted' },
};

const STATUS_OPTIONS = [
  'available',
  'under_testing',
  'coming_soon',
  'unavailable',
  'disabled',
] as const;

interface EditForm {
  status: string;
  message: string;
  eta: string;
  isEnabled: boolean;
  allowKey: boolean;
}

function statusMeta(status: string) {
  return STATUS_META[status] ?? { label: status, tone: 'muted' as PillTone };
}

function toDatetimeLocal(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate()
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function buildPayload(
  provider: AdminProviderRead,
  form: EditForm
): AdminProviderUpdate {
  const payload: AdminProviderUpdate = {};
  if (form.status !== provider.status) payload.status = form.status;
  if (form.isEnabled !== provider.is_enabled) payload.is_enabled = form.isEnabled;
  if (form.message.trim() !== (provider.status_message ?? '')) {
    payload.status_message = form.message.trim() || null;
  }
  if (form.eta !== toDatetimeLocal(provider.status_expires_at)) {
    payload.status_expires_at = form.eta
      ? new Date(form.eta).toISOString()
      : null;
  }
  if (form.allowKey !== provider.allow_key_addition) {
    payload.allow_key_addition = form.allowKey;
  }
  // Never send contradictory master-switch/status pairs (409 server-side).
  if (
    payload.is_enabled === false &&
    payload.status &&
    payload.status !== 'disabled'
  ) {
    delete payload.status;
  }
  if (payload.is_enabled === true && payload.status === 'disabled') {
    delete payload.status;
  }
  return payload;
}

function errorDetail(error: unknown): string | undefined {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  return undefined;
}

const fieldLabelCls = 'block text-xs font-medium text-muted-foreground mb-1';
const fieldCls =
  'w-full h-11 rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';

export default function AdminProvidersPage() {
  const [editing, setEditing] = useState<AdminProviderRead | null>(null);
  const [form, setForm] = useState<EditForm | null>(null);
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['admin', 'providers'],
    queryFn: adminApi.providers,
    retry: 1,
  });

  const updateMutation = useMutation({
    mutationFn: ({ slug, payload }: { slug: string; payload: AdminProviderUpdate }) =>
      adminApi.updateProvider(slug, payload),
    onSuccess: (provider) => {
      toast({
        title: `${provider.display_name} updated`,
        description: 'The change is live and has been audited.',
        type: 'success',
      });
      setEditing(null);
      setForm(null);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'providers'] });
    },
    onError: (error) => {
      toast({
        title: 'Could not update provider',
        description: errorDetail(error),
        type: 'error',
      });
    },
  });

  const openEdit = (provider: AdminProviderRead) => {
    setEditing(provider);
    setForm({
      status: provider.status,
      message: provider.status_message ?? '',
      eta: toDatetimeLocal(provider.status_expires_at),
      isEnabled: provider.is_enabled,
      allowKey: provider.allow_key_addition,
    });
  };

  const closeEdit = () => {
    if (updateMutation.isPending) return;
    setEditing(null);
    setForm(null);
  };

  const payload =
    editing && form ? buildPayload(editing, form) : ({} as AdminProviderUpdate);
  const hasChanges = Object.keys(payload).length > 0;

  const columns: DataTableColumn<AdminProviderRead>[] = [
    {
      key: 'provider',
      header: 'Provider',
      render: (provider) => (
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="shrink-0 flex items-center justify-center w-8 h-8 rounded-lg bg-surface-2 border border-border">
            <ProviderIcon slug={provider.slug} size={16} />
          </span>
          <p
            className="font-medium text-foreground truncate"
            title={provider.slug}
          >
            {provider.display_name}
          </p>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (provider) => {
        const meta = statusMeta(provider.status);
        return (
          <div className="min-w-0 max-w-[260px]">
            <Pill tone={meta.tone}>{meta.label}</Pill>
            {provider.status_message && (
              <p className="mt-1 text-xs text-muted-foreground break-words">
                {provider.status_message}
              </p>
            )}
            {provider.status_expires_at && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                Until {formatDateTime(provider.status_expires_at)}
              </p>
            )}
          </div>
        );
      },
    },
    {
      key: 'enabled',
      header: 'Master switch',
      render: (provider) => (
        <Pill tone={provider.is_enabled ? 'success' : 'muted'}>
          {provider.is_enabled ? 'Enabled' : 'Disabled'}
        </Pill>
      ),
    },
    {
      key: 'key_policy',
      header: 'New keys',
      render: (provider) => (
        <Pill tone={provider.allow_key_addition ? 'success' : 'warning'}>
          {provider.allow_key_addition ? 'Allowed' : 'Blocked'}
        </Pill>
      ),
    },
    {
      key: 'keys',
      header: 'Keys',
      render: (provider) => (
        <span className="text-muted-foreground whitespace-nowrap tabular-nums">
          {provider.keys_enabled}/{provider.keys_total} enabled ·{' '}
          {provider.keys_valid} valid
        </span>
      ),
    },
    {
      key: 'mappings',
      header: 'Repo mappings',
      className: 'text-right',
      render: (provider) => (
        <span className="tabular-nums">{provider.mapped_repositories}</span>
      ),
    },
    {
      key: 'health',
      header: 'Last health',
      className: 'whitespace-nowrap',
      render: (provider) => (
        <div>
          {provider.last_health_status ? (
            <Pill tone={statusMeta(provider.last_health_status).tone}>
              {provider.last_health_status}
            </Pill>
          ) : (
            <span className="text-muted-foreground">Not recorded</span>
          )}
          {provider.last_health_at && (
            <p className="mt-1 text-xs text-muted-foreground">
              {formatDateTime(provider.last_health_at)}
            </p>
          )}
        </div>
      ),
    },
    {
      key: 'actions',
      header: '',
      className: 'text-right',
      render: (provider) => (
        <button
          type="button"
          onClick={() => openEdit(provider)}
          className="inline-flex items-center gap-2 h-11 px-3 rounded-lg border border-border text-sm font-medium text-foreground/80 hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          <Pencil size={15} />
          Edit
        </button>
      ),
    },
  ];

  return (
    <div>
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
          Providers
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Availability, messages, master switches and key-addition policy. Every
          change is audited; credentials, mappings and history are never touched.
        </p>
      </div>

      {isError && !isPending && (
        <div
          role="alert"
          className="mt-4 flex items-center gap-3 rounded-xl border border-error/40 bg-error/10 p-4 text-sm text-error"
        >
          <AlertTriangle size={18} className="shrink-0" />
          <span>
            Could not load providers.{' '}
            <button
              type="button"
              onClick={() => refetch()}
              className="underline underline-offset-2 cursor-pointer"
            >
              Try again
            </button>
          </span>
        </div>
      )}

      <div className="mt-4">
        <DataTable
          columns={columns}
          rows={data?.items ?? []}
          keyOf={(provider) => provider.id}
          isLoading={isPending}
          empty={
            <EmptyState
              icon={<Server size={22} />}
              title="No providers registered"
              description="The provider registry is empty. Seed it via the platform migrations."
            />
          }
          renderMobileCard={(provider) => {
            const meta = statusMeta(provider.status);
            return (
              <div className="rounded-xl border border-border bg-surface-1 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <ProviderIcon slug={provider.slug} size={16} />
                    <p
                      className="font-medium text-foreground truncate"
                      title={provider.slug}
                    >
                      {provider.display_name}
                    </p>
                  </div>
                  <Pill tone={meta.tone}>{meta.label}</Pill>
                </div>
                {provider.status_message && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {provider.status_message}
                  </p>
                )}
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <div>
                    <dt>Master switch</dt>
                    <dd className="text-foreground">
                      {provider.is_enabled ? 'Enabled' : 'Disabled'}
                    </dd>
                  </div>
                  <div>
                    <dt>New keys</dt>
                    <dd className="text-foreground">
                      {provider.allow_key_addition ? 'Allowed' : 'Blocked'}
                    </dd>
                  </div>
                  <div>
                    <dt>Keys</dt>
                    <dd className="text-foreground tabular-nums">
                      {provider.keys_enabled}/{provider.keys_total} ·{' '}
                      {provider.keys_valid} valid
                    </dd>
                  </div>
                  <div>
                    <dt>Repo mappings</dt>
                    <dd className="text-foreground tabular-nums">
                      {provider.mapped_repositories}
                    </dd>
                  </div>
                </dl>
                <button
                  type="button"
                  onClick={() => openEdit(provider)}
                  className="mt-3 inline-flex items-center gap-2 h-11 px-3 rounded-lg border border-border text-sm font-medium text-foreground/80 hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  <Pencil size={15} />
                  Edit
                </button>
              </div>
            );
          }}
          ariaLabel="Providers"
        />
      </div>

      <ConfirmDialog
        open={editing !== null && form !== null}
        title={editing ? `Edit ${editing.display_name}` : 'Edit provider'}
        description="Status and policy changes apply immediately and are written to the audit log."
        confirmLabel="Save changes"
        busy={updateMutation.isPending}
        confirmDisabled={!hasChanges}
        onConfirm={() => {
          if (editing && hasChanges) {
            updateMutation.mutate({ slug: editing.slug, payload });
          }
        }}
        onCancel={closeEdit}
      >
        {form && (
          <div className="space-y-3">
            <div>
              <label htmlFor="provider-status" className={fieldLabelCls}>
                Lifecycle status
              </label>
              <select
                id="provider-status"
                value={form.status}
                onChange={(event) => {
                  const value = event.target.value;
                  setForm((current) =>
                    current
                      ? {
                          ...current,
                          status: value,
                          isEnabled:
                            value === 'disabled' ? false : current.isEnabled,
                        }
                      : current
                  );
                }}
                className={fieldCls}
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {statusMeta(option).label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="provider-message" className={fieldLabelCls}>
                User-facing message (optional)
              </label>
              <textarea
                id="provider-message"
                value={form.message}
                maxLength={500}
                rows={3}
                onChange={(event) =>
                  setForm((current) =>
                    current ? { ...current, message: event.target.value } : current
                  )
                }
                placeholder="Shown to users wherever the provider is blocked."
                className="w-full rounded-lg border border-border bg-surface-1 px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              />
            </div>

            <div>
              <label htmlFor="provider-eta" className={fieldLabelCls}>
                Expected back (optional)
              </label>
              <input
                id="provider-eta"
                type="datetime-local"
                value={form.eta}
                onChange={(event) =>
                  setForm((current) =>
                    current ? { ...current, eta: event.target.value } : current
                  )
                }
                className={fieldCls}
              />
            </div>

            <label className="flex items-start gap-3 min-h-11 py-1 cursor-pointer">
              <input
                type="checkbox"
                checked={form.isEnabled}
                onChange={(event) => {
                  const next = event.target.checked;
                  setForm((current) =>
                    current
                      ? {
                          ...current,
                          isEnabled: next,
                          status: next
                            ? current.status === 'disabled'
                              ? 'available'
                              : current.status
                            : 'disabled',
                        }
                      : current
                  );
                }}
                className="mt-0.5 h-4 w-4 rounded border-border text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              />
              <span>
                <span className="block text-sm text-foreground">
                  Provider enabled (master switch)
                </span>
                <span className="block text-xs text-muted-foreground">
                  Turning it off sets the status to Disabled; turning it back on
                  restores availability without any user reconfiguration.
                </span>
              </span>
            </label>

            <label className="flex items-start gap-3 min-h-11 py-1 cursor-pointer">
              <input
                type="checkbox"
                checked={form.allowKey}
                onChange={(event) => {
                  const next = event.target.checked;
                  setForm((current) =>
                    current ? { ...current, allowKey: next } : current
                  );
                }}
                className="mt-0.5 h-4 w-4 rounded border-border text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              />
              <span>
                <span className="block text-sm text-foreground">
                  Allow users to add new API keys
                </span>
                <span className="block text-xs text-muted-foreground">
                  Existing keys remain stored and rotatable either way.
                </span>
              </span>
            </label>
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
