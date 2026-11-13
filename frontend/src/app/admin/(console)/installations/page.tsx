'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { GitBranch } from 'lucide-react';
import { adminApi, type AdminInstallationItem } from '@/lib/api';
import { DataTable, type DataTableColumn } from '@/components/shared/data-table';
import { EmptyState } from '@/components/shared/empty-state';
import { Pagination } from '@/components/shared/pagination';
import { Pill, toneForStatus } from '@/components/shared/pill';
import { TextFilter } from '@/components/shared/text-filter';
import { formatDateTime } from '@/components/shared/time-ago';
import { AdminPage } from '@/components/admin/page-shell';
import { FilterBar, SelectFilter } from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  suspended: 'Suspended',
  inaccessible: 'Inaccessible',
  reauthorization_required: 'Reauthorization required',
  configuration_error: 'Configuration error',
};

const STATUS_OPTIONS = Object.keys(STATUS_LABELS);

function humanize(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? humanize(status);
}

function permissionsMeta(value: boolean | null): {
  label: string;
  tone: 'success' | 'error' | 'muted';
} {
  if (value === null) return { label: 'Unknown', tone: 'muted' };
  return value
    ? { label: 'OK', tone: 'success' }
    : { label: 'Missing', tone: 'error' };
}

export default function AdminInstallationsPage() {
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['admin', 'installations', status, q, offset],
    queryFn: () =>
      adminApi.installations({
        status: status || undefined,
        q: q || undefined,
        limit,
        offset,
      }),
    retry: 1,
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const filtersActive = Boolean(status || q);

  const columns: DataTableColumn<AdminInstallationItem>[] = [
    {
      key: 'account',
      header: 'Account',
      render: (item) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-foreground">
            {item.account_login ?? 'Unknown account'}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {[item.account_type, item.target_type]
              .filter(Boolean)
              .map((value) => humanize(value as string))
              .join(' / ') || 'GitHub App installation'}
          </p>
        </div>
      ),
    },
    {
      key: 'installation',
      header: 'Installation',
      render: (item) => (
        <div className="min-w-0">
          <p className="admin-figure text-xs text-foreground">
            {item.installation_id}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            App {item.app_id ?? 'unknown'}
          </p>
        </div>
      ),
    },
    {
      key: 'lifecycle',
      header: 'Lifecycle',
      render: (item) => (
        <div className="min-w-0">
          <Pill tone={toneForStatus(item.lifecycle_status)} dot>
            {statusLabel(item.lifecycle_status)}
          </Pill>
          {item.suspended_at && (
            <p className="mt-1 text-xs text-muted-foreground">
              Since {formatDateTime(item.suspended_at)}
            </p>
          )}
        </div>
      ),
    },
    {
      key: 'access',
      header: 'Permissions',
      render: (item) => {
        const meta = permissionsMeta(item.permissions_ok);
        return (
          <div className="min-w-0">
            <Pill tone={meta.tone} dot>
              {meta.label}
            </Pill>
            {item.last_auth_error_category && (
              <p className="mt-1 text-xs text-muted-foreground">
                {humanize(item.last_auth_error_category)}
              </p>
            )}
          </div>
        );
      },
    },
    {
      key: 'repos',
      header: 'Repos',
      className: 'text-right',
      render: (item) => (
        <span className="admin-figure">{item.repository_count}</span>
      ),
    },
    {
      key: 'auth',
      header: 'Last auth check',
      render: (item) => (
        <div className="min-w-0">
          <p className="text-xs text-foreground">
            {formatDateTime(item.last_auth_checked_at) || 'Never checked'}
          </p>
          {item.retry_after && (
            <p className="mt-0.5 text-xs text-warning">
              Retry after {formatDateTime(item.retry_after)}
            </p>
          )}
          {item.auth_failure_count > 0 && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {item.auth_failure_count} failure
              {item.auth_failure_count === 1 ? '' : 's'}
            </p>
          )}
        </div>
      ),
    },
    {
      key: 'sync',
      header: 'Last sync',
      render: (item) => (
        <div className="min-w-0 max-w-56">
          <p className="text-xs text-foreground">
            {item.last_sync_status
              ? humanize(item.last_sync_status)
              : 'Not synced'}
          </p>
          {item.last_sync_completed_at && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {formatDateTime(item.last_sync_completed_at)}
            </p>
          )}
          {item.last_sync_error && (
            <p
              className="mt-0.5 truncate text-xs text-error"
              title={item.last_sync_error}
            >
              {item.last_sync_error}
            </p>
          )}
        </div>
      ),
    },
  ];

  return (
    <AdminPage
      eyebrow="Access"
      title="Installations"
      description={
        filtersActive
          ? `${items.length} of ${total} GitHub App installations`
          : 'GitHub App installations, lifecycle state, permission health and sync recovery.'
      }
    >
      {isError && !isLoading && (
        <QueryError
          message="Could not load installations."
          onRetry={() => refetch()}
        />
      )}

      <FilterBar label="Installation filters">
        <TextFilter
          value={q}
          onChange={(value) => {
            setQ(value);
            setOffset(0);
          }}
          placeholder="Search account or installation ID…"
          ariaLabel="Search installations"
          className="w-full sm:w-72"
        />
        <SelectFilter
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter by lifecycle status"
          className="w-full sm:w-56"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {statusLabel(option)}
            </option>
          ))}
        </SelectFilter>
      </FilterBar>

      <DataTable
        columns={columns}
        rows={items}
        keyOf={(item) => item.id}
        isLoading={isLoading}
        empty={
          <EmptyState
            icon={<GitBranch size={22} />}
            title={
              filtersActive ? 'No matching installations' : 'No installations'
            }
            description={
              filtersActive
                ? 'Try a different search or clear the lifecycle filter.'
                : 'Installations appear here after a user connects the GitHub App to an account.'
            }
          />
        }
        ariaLabel="GitHub App installations"
        renderMobileCard={(item) => {
          const lifecycle = statusLabel(item.lifecycle_status);
          const access = permissionsMeta(item.permissions_ok);
          return (
            <div className="space-y-3 rounded-xl border border-border bg-surface-1 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">
                    {item.account_login ?? 'Unknown account'}
                  </p>
                  <p className="admin-figure mt-0.5 text-xs text-muted-foreground">
                    Installation {item.installation_id} · App{' '}
                    {item.app_id ?? 'unknown'}
                  </p>
                </div>
                <Pill tone={toneForStatus(item.lifecycle_status)} dot>
                  {lifecycle}
                </Pill>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={access.tone} dot>
                  Permissions {access.label}
                </Pill>
                <Pill tone="muted">{item.repository_count} repos</Pill>
                {item.auth_failure_count > 0 && (
                  <Pill tone="warning">
                    {item.auth_failure_count} auth failure
                    {item.auth_failure_count === 1 ? '' : 's'}
                  </Pill>
                )}
              </div>

              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <dt className="text-muted-foreground">Last auth check</dt>
                  <dd className="mt-0.5 text-foreground">
                    {formatDateTime(item.last_auth_checked_at) || 'Never'}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Retry after</dt>
                  <dd className="mt-0.5 text-foreground">
                    {formatDateTime(item.retry_after) || 'Not scheduled'}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-muted-foreground">Last sync</dt>
                  <dd className="mt-0.5 text-foreground">
                    {item.last_sync_status
                      ? humanize(item.last_sync_status)
                      : 'Not synced'}
                    {item.last_sync_completed_at
                      ? ` · ${formatDateTime(item.last_sync_completed_at)}`
                      : ''}
                  </dd>
                  {item.last_sync_error && (
                    <dd className="mt-0.5 break-words text-error">
                      {item.last_sync_error}
                    </dd>
                  )}
                </div>
                {item.last_auth_error_category && (
                  <div className="col-span-2">
                    <dt className="text-muted-foreground">
                      Auth error category
                    </dt>
                    <dd className="mt-0.5 text-foreground">
                      {humanize(item.last_auth_error_category)}
                    </dd>
                  </div>
                )}
              </dl>
            </div>
          );
        }}
      />

      {total > 0 && (
        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          onChange={setOffset}
        />
      )}
    </AdminPage>
  );
}
