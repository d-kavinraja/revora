'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FolderGit2 } from 'lucide-react';
import {
  adminApi,
  type AdminRepositoryItem,
} from '@/lib/api';
import { DataTable, type DataTableColumn } from '@/components/shared/data-table';
import { Pagination } from '@/components/shared/pagination';
import { EmptyState } from '@/components/shared/empty-state';
import { Pill, toneForStatus } from '@/components/shared/pill';
import { TextFilter } from '@/components/shared/text-filter';
import { formatDateTime } from '@/components/shared/time-ago';
import { AdminPage } from '@/components/admin/page-shell';
import { FilterBar, SelectFilter } from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

const PAGE_SIZE = 25;

type MappingFilter = '' | 'ok' | 'stale' | 'missing';

function MappingCell({ repo }: { repo: AdminRepositoryItem }) {
  return (
    <div className="flex min-w-0 max-w-[280px] items-center gap-2">
      <span className="max-w-[220px] truncate text-foreground/80">
        {repo.mapping_provider || repo.mapping_model ? (
          <>
            {repo.mapping_provider ?? 'Unset'}
            {repo.mapping_model ? ` · ${repo.mapping_model}` : ''}
          </>
        ) : (
          <span className="text-muted-foreground">Not configured</span>
        )}
      </span>
      <Pill tone={toneForStatus(repo.mapping_health)} dot>
        {repo.mapping_health}
      </Pill>
    </div>
  );
}

function RepoIdentity({ repo }: { repo: AdminRepositoryItem }) {
  return (
    <div className="min-w-0">
      <p className="max-w-[260px] truncate font-medium text-foreground" title={repo.full_name}>
        {repo.full_name}
      </p>
      <p className="text-xs text-muted-foreground">
        {[
          repo.is_private ? 'Private' : 'Public',
          repo.is_archived ? 'Archived' : null,
          repo.removed_at ? 'Removed' : null,
        ]
          .filter(Boolean)
          .join(' · ')}
      </p>
    </div>
  );
}

export default function AdminRepositoriesPage() {
  const [user, setUser] = useState('');
  const [provider, setProvider] = useState('');
  const [mapping, setMapping] = useState<MappingFilter>('');
  const [offset, setOffset] = useState(0);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['admin', 'repositories', { user, provider, mapping, offset }],
    queryFn: () =>
      adminApi.repositories({
        user: user || undefined,
        provider: provider || undefined,
        mapping: mapping || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    retry: 1,
  });

  const columns: DataTableColumn<AdminRepositoryItem>[] = [
    {
      key: 'repo',
      header: 'Repository',
      render: (repo) => <RepoIdentity repo={repo} />,
    },
    {
      key: 'owner',
      header: 'Owner',
      render: (repo) => (
        <div className="min-w-0">
          <p className="max-w-[220px] truncate text-foreground/80" title={repo.owner_email}>
            {repo.owner_email}
          </p>
          {repo.owner_github_username && (
            <p className="text-xs text-muted-foreground">
              @{repo.owner_github_username}
            </p>
          )}
        </div>
      ),
    },
    {
      key: 'installation',
      header: 'Installation',
      className: 'whitespace-nowrap',
      render: (repo) => (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-foreground/80">
            {repo.installation_account_login ?? '—'}
          </span>
          {repo.installation_suspended_at && (
            <Pill tone="error" dot>
              Suspended
            </Pill>
          )}
          {repo.installation_permissions_ok === false && (
            <Pill tone="warning" dot>
              Perms issue
            </Pill>
          )}
        </div>
      ),
    },
    {
      key: 'mapping',
      header: 'Mapping',
      render: (repo) => <MappingCell repo={repo} />,
    },
    {
      key: 'reviews',
      header: 'Reviews',
      className: 'text-right',
      render: (repo) => (
        <div className="text-right">
          <p className="admin-figure text-foreground">{repo.review_count}</p>
          <p className="admin-figure whitespace-nowrap text-xs text-muted-foreground">
            {repo.last_review_at ? formatDateTime(repo.last_review_at) : '—'}
          </p>
        </div>
      ),
    },
    {
      key: 'failures',
      header: 'Failures 7d',
      className: 'text-right',
      render: (repo) => (
        <span
          className={`admin-figure ${
            repo.recent_failures_7d > 0 ? 'text-error' : 'text-muted-foreground'
          }`}
        >
          {repo.recent_failures_7d}
        </span>
      ),
    },
    {
      key: 'synced',
      header: 'Last synced',
      className: 'whitespace-nowrap',
      render: (repo) => (
        <span className="admin-figure whitespace-nowrap text-muted-foreground">
          {repo.last_synced_at ? formatDateTime(repo.last_synced_at) : '—'}
        </span>
      ),
    },
  ];

  return (
    <AdminPage
      eyebrow="Manage"
      title="Repositories"
      description={
        data
          ? `${data.total.toLocaleString()} repositor${
              data.total === 1 ? 'y' : 'ies'
            }`
          : 'Connected repositories, owners, and provider mappings.'
      }
    >
      <FilterBar label="Repository filters">
        <TextFilter
          value={user}
          onChange={(value) => {
            setUser(value);
            setOffset(0);
          }}
          placeholder="Owner email or GitHub…"
          ariaLabel="Filter by owner"
          className="w-full sm:w-60"
        />
        <TextFilter
          value={provider}
          onChange={(value) => {
            setProvider(value);
            setOffset(0);
          }}
          placeholder="Provider…"
          ariaLabel="Filter by provider"
          className="w-full sm:w-44"
        />
        <SelectFilter
          value={mapping}
          onChange={(event) => {
            setMapping(event.target.value as MappingFilter);
            setOffset(0);
          }}
          aria-label="Filter by mapping health"
          className="w-full sm:w-44"
        >
          <option value="">All mappings</option>
          <option value="ok">Healthy (ok)</option>
          <option value="stale">Stale</option>
          <option value="missing">Missing</option>
        </SelectFilter>
      </FilterBar>

      {isError && !isPending && (
        <QueryError
          message="Could not load repositories."
          onRetry={() => refetch()}
        />
      )}

      <DataTable
        columns={columns}
        rows={data?.items ?? []}
        keyOf={(repo) => repo.id}
        isLoading={isPending}
        empty={
          <EmptyState
            icon={<FolderGit2 size={22} />}
            title="No repositories found"
            description={
              user || provider || mapping
                ? 'No repositories match the current filters.'
                : 'No repositories have been connected yet.'
            }
          />
        }
        renderMobileCard={(repo) => (
          <div className="rounded-xl border border-border bg-surface-1 p-4">
            <div className="flex items-start justify-between gap-3">
              <RepoIdentity repo={repo} />
              <Pill tone={toneForStatus(repo.mapping_health)} dot>
                {repo.mapping_health}
              </Pill>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {repo.owner_email}
              {repo.owner_github_username ? ` (@${repo.owner_github_username})` : ''}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {repo.mapping_provider
                ? `${repo.mapping_provider}${repo.mapping_model ? ` · ${repo.mapping_model}` : ''}`
                : 'No mapping configured'}
            </p>
            <p className="admin-figure mt-1 text-xs text-muted-foreground">
              {repo.review_count} reviews ·{' '}
              <span className={repo.recent_failures_7d > 0 ? 'text-error' : ''}>
                {repo.recent_failures_7d} failures (7d)
              </span>
              {repo.installation_suspended_at ? ' · Suspended' : ''}
            </p>
          </div>
        )}
        ariaLabel="Repositories"
      />

      {data && (
        <Pagination
          total={data.total}
          limit={data.limit}
          offset={data.offset}
          onChange={setOffset}
        />
      )}
    </AdminPage>
  );
}
