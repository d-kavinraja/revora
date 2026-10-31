'use client';

import { useState } from 'react';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Server } from 'lucide-react';
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
import { AdminPage } from '@/components/admin/page-shell';
import {
  AdminButton,
  ADMIN_INPUT_CLASS,
  ADMIN_LABEL_CLASS,
  ADMIN_TEXTAREA_CLASS,
  CheckboxRow,
  Field,
} from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

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
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2">
            <ProviderIcon slug={provider.slug} size={16} />
          </span>
          <p className="truncate font-medium text-foreground" title={provider.slug}>
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
            <Pill tone={meta.tone} dot>
              {meta.label}
            </Pill>
            {provider.status_message && (
              <p className="mt-1 break-words text-xs text-muted-foreground">
                {provider.status_message}
              </p>
            )}
            {provider.status_expires_at && (
              <p className="admin-figure mt-0.5 text-xs text-muted-foreground">
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
        <Pill tone={provider.is_enabled ? 'success' : 'muted'} dot>
          {provider.is_enabled ? 'Enabled' : 'Disabled'}
        </Pill>
      ),
    },
    {
      key: 'key_policy',
      header: 'New keys',
      render: (provider) => (
        <Pill tone={provider.allow_key_addition ? 'success' : 'warning'} dot>
          {provider.allow_key_addition ? 'Allowed' : 'Blocked'}
        </Pill>
      ),
    },
    {
      key: 'keys',
      header: 'Keys',
      render: (provider) => (
        <span className="admin-figure whitespace-nowrap text-muted-foreground">
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
        <span className="admin-figure">{provider.mapped_repositories}</span>
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
            <p className="admin-figure mt-1 text-xs text-muted-foreground">
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
        <AdminButton variant="secondary" size="sm" onClick={() => openEdit(provider)}>
          <Pencil size={14} />
          Edit
        </AdminButton>
      ),
    },
  ];

  return (
    <AdminPage
      eyebrow="System"
      title="Providers"
      description="Availability, messages, master switches and key-addition policy. Every change is audited; credentials, mappings and history are never touched."
    >
      {isError && !isPending && (
        <QueryError message="Could not load providers." onRetry={() => refetch()} />
      )}

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
                <div className="flex min-w-0 items-center gap-2.5">
                  <ProviderIcon slug={provider.slug} size={16} />
                  <p className="truncate font-medium text-foreground" title={provider.slug}>
                    {provider.display_name}
                  </p>
                </div>
                <Pill tone={meta.tone} dot>
                  {meta.label}
                </Pill>
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
                  <dd className="admin-figure text-foreground">
                    {provider.keys_enabled}/{provider.keys_total} ·{' '}
                    {provider.keys_valid} valid
                  </dd>
                </div>
                <div>
                  <dt>Repo mappings</dt>
                  <dd className="admin-figure text-foreground">
                    {provider.mapped_repositories}
                  </dd>
                </div>
              </dl>
              <AdminButton
                variant="secondary"
                size="sm"
                className="mt-3"
                onClick={() => openEdit(provider)}
              >
                <Pencil size={14} />
                Edit
              </AdminButton>
            </div>
          );
        }}
        ariaLabel="Providers"
      />

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
            <Field label="Lifecycle status" htmlFor="provider-status">
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
                className={`${ADMIN_INPUT_CLASS} cursor-pointer`}
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {statusMeta(option).label}
                  </option>
                ))}
              </select>
            </Field>

            <div>
              <label htmlFor="provider-message" className={ADMIN_LABEL_CLASS}>
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
                className={ADMIN_TEXTAREA_CLASS}
              />
            </div>

            <Field label="Expected back (optional)" htmlFor="provider-eta">
              <input
                id="provider-eta"
                type="datetime-local"
                value={form.eta}
                onChange={(event) =>
                  setForm((current) =>
                    current ? { ...current, eta: event.target.value } : current
                  )
                }
                className={ADMIN_INPUT_CLASS}
              />
            </Field>

            <CheckboxRow
              checked={form.isEnabled}
              onChange={(next) => {
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
              title="Provider enabled (master switch)"
              description="Turning it off sets the status to Disabled; turning it back on restores availability without any user reconfiguration."
            />

            <CheckboxRow
              checked={form.allowKey}
              onChange={(next) => {
                setForm((current) =>
                  current ? { ...current, allowKey: next } : current
                );
              }}
              title="Allow users to add new API keys"
              description="Existing keys remain stored and rotatable either way."
            />
          </div>
        )}
      </ConfirmDialog>
    </AdminPage>
  );
}
