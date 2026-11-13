'use client';

import { useMemo, useState } from 'react';
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
import { TextFilter } from '@/components/shared/text-filter';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { ProviderBadge } from '@/components/ui/provider-brand';
import { useToast } from '@/components/ui/toaster';
import {
  formatDateTime,
  fromDatetimeLocalValue,
  toDatetimeLocalValue,
} from '@/components/shared/time-ago';
import { AdminPage } from '@/components/admin/page-shell';
import {
  AdminButton,
  AdminSwitch,
  ADMIN_INPUT_CLASS,
  ADMIN_LABEL_CLASS,
  ADMIN_TEXTAREA_CLASS,
  Field,
  FilterBar,
  SelectFilter,
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

const EMPTY_PROVIDERS: AdminProviderRead[] = [];

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
  if (form.eta !== toDatetimeLocalValue(provider.status_expires_at)) {
    payload.status_expires_at = fromDatetimeLocalValue(form.eta);
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
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [enabledFilter, setEnabledFilter] = useState('');
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
      eta: toDatetimeLocalValue(provider.status_expires_at),
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

  const items = data?.items ?? EMPTY_PROVIDERS;
  const filteredItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    return items.filter((provider) => {
      const matchesQuery =
        !query ||
        provider.display_name.toLowerCase().includes(query) ||
        provider.slug.toLowerCase().includes(query);
      const matchesStatus = !statusFilter || provider.status === statusFilter;
      const matchesEnabled =
        !enabledFilter ||
        (enabledFilter === 'enabled' ? provider.is_enabled : !provider.is_enabled);
      return matchesQuery && matchesStatus && matchesEnabled;
    });
  }, [items, search, statusFilter, enabledFilter]);
  const filtersActive = Boolean(search || statusFilter || enabledFilter);

  const columns: DataTableColumn<AdminProviderRead>[] = [
    {
      key: 'provider',
      header: 'Provider',
      render: (provider) => (
        <ProviderBadge
          slug={provider.slug}
          label={provider.display_name}
          className="max-w-56"
        />
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
      description={
        filtersActive
          ? `${filteredItems.length} of ${items.length} providers`
          : 'Availability, messages, master switches and key-addition policy. Credentials, mappings and history are never touched.'
      }
    >
      {isError && !isPending && (
        <QueryError message="Could not load providers." onRetry={() => refetch()} />
      )}

      <FilterBar label="Provider filters">
        <TextFilter
          value={search}
          onChange={setSearch}
          placeholder="Search providers…"
          ariaLabel="Search providers"
          className="w-full sm:w-64"
        />
        <SelectFilter
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          aria-label="Filter by lifecycle status"
          className="w-full sm:w-52"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {statusMeta(option).label}
            </option>
          ))}
        </SelectFilter>
        <SelectFilter
          value={enabledFilter}
          onChange={(event) => setEnabledFilter(event.target.value)}
          aria-label="Filter by master switch"
          className="w-full sm:w-44"
        >
          <option value="">Enabled and disabled</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
        </SelectFilter>
      </FilterBar>

      <DataTable
        columns={columns}
        rows={filteredItems}
        keyOf={(provider) => provider.id}
        isLoading={isPending}
        empty={
          <EmptyState
            icon={<Server size={22} />}
            title={filtersActive ? 'No matching providers' : 'No providers registered'}
            description={
              filtersActive
                ? 'Try a different search or clear the filters.'
                : 'The provider registry is empty. Seed it via the platform migrations.'
            }
          />
        }
        renderMobileCard={(provider) => {
          const meta = statusMeta(provider.status);
          return (
            <div className="rounded-xl border border-border bg-surface-1 p-4">
              <div className="flex items-start justify-between gap-3">
                <ProviderBadge
                  slug={provider.slug}
                  label={provider.display_name}
                  size="sm"
                  className="max-w-48"
                />
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

            <div className="grid gap-3 rounded-lg border border-border bg-surface-2/50 p-3 sm:grid-cols-2">
              <AdminSwitch
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
                title="Provider enabled"
                description="Turning it off sets the status to Disabled. Turning it back on restores availability without user reconfiguration."
              />
              <AdminSwitch
                checked={form.allowKey}
                onChange={(next) => {
                  setForm((current) =>
                    current ? { ...current, allowKey: next } : current
                  );
                }}
                title="Allow new API keys"
                description="Existing keys remain stored and rotatable either way."
              />
            </div>
          </div>
        )}
      </ConfirmDialog>
    </AdminPage>
  );
}
