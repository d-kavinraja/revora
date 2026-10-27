'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Users as UsersIcon } from 'lucide-react';
import {
  adminApi,
  type AdminUserListItem,
  type AdminUserStatusFilter,
} from '@/lib/api';
import { DataTable, type DataTableColumn } from '@/components/shared/data-table';
import { Pagination } from '@/components/shared/pagination';
import { EmptyState } from '@/components/shared/empty-state';
import { Pill, toneForStatus } from '@/components/shared/pill';
import { TextFilter } from '@/components/shared/text-filter';
import { formatDateTime } from '@/components/shared/time-ago';

const PAGE_SIZE = 25;

function UserIdentity({ user }: { user: AdminUserListItem }) {
  return (
    <div className="min-w-0">
      <Link
        href={`/admin/users/${user.id}`}
        className="font-medium text-foreground hover:text-brand transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded"
      >
        {user.name || '—'}
      </Link>
      <p className="text-xs text-muted-foreground truncate max-w-[220px]" title={user.email}>{user.email}</p>
    </div>
  );
}

export default function AdminUsersPage() {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<AdminUserStatusFilter | ''>('');
  const [sort, setSort] = useState<'created' | 'last_login' | 'reviews'>('created');
  const [offset, setOffset] = useState(0);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['admin', 'users', { q, status, sort, offset }],
    queryFn: () =>
      adminApi.users({
        q: q || undefined,
        status: status || undefined,
        sort,
        limit: PAGE_SIZE,
        offset,
      }),
    retry: 1,
  });

  const columns: DataTableColumn<AdminUserListItem>[] = [
    {
      key: 'user',
      header: 'User',
      render: (user) => <UserIdentity user={user} />,
    },
    {
      key: 'github',
      header: 'GitHub',
      render: (user) => (
        <span className="text-muted-foreground">
          {user.github_username ? `@${user.github_username}` : '—'}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (user) => (
        <Pill tone={toneForStatus(user.status)}>{user.status}</Pill>
      ),
    },
    {
      key: 'repos',
      header: 'Repos',
      className: 'text-right',
      render: (user) => <span className="tabular-nums">{user.repo_count}</span>,
    },
    {
      key: 'credentials',
      header: 'Credentials',
      className: 'text-right',
      render: (user) => (
        <span className="tabular-nums">{user.credential_count}</span>
      ),
    },
    {
      key: 'reviews',
      header: 'Reviews',
      className: 'text-right',
      render: (user) => <span className="tabular-nums">{user.review_count}</span>,
    },
    {
      key: 'created',
      header: 'Created',
      className: 'whitespace-nowrap',
      render: (user) => (
        <span className="text-muted-foreground whitespace-nowrap">
          {formatDateTime(user.created_at)}
        </span>
      ),
    },
    {
      key: 'last_login',
      header: 'Last login',
      className: 'whitespace-nowrap',
      render: (user) => (
        <span className="text-muted-foreground whitespace-nowrap">
          {user.last_login_at ? formatDateTime(user.last_login_at) : '—'}
        </span>
      ),
    },
  ];

  const filterCls =
    'min-w-0 max-w-[220px] h-11 rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
            Users
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {data
              ? `${data.total.toLocaleString()} registered user${
                  data.total === 1 ? '' : 's'
                }`
              : 'Registered accounts and their activity.'}
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <TextFilter
          value={q}
          onChange={(value) => {
            setQ(value);
            setOffset(0);
          }}
          placeholder="Search name, email, GitHub…"
          ariaLabel="Search users"
          className="w-full sm:w-64"
        />
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as AdminUserStatusFilter | '');
            setOffset(0);
          }}
          aria-label="Filter by status"
          className={filterCls}
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
        </select>
        <select
          value={sort}
          onChange={(event) => {
            setSort(event.target.value as 'created' | 'last_login' | 'reviews');
            setOffset(0);
          }}
          aria-label="Sort users"
          className={filterCls}
        >
          <option value="created">Newest first</option>
          <option value="last_login">Last login</option>
          <option value="reviews">Most reviews</option>
        </select>
      </div>

      {isError && !isPending && (
        <div
          role="alert"
          className="mt-4 flex items-center gap-3 rounded-xl border border-error/40 bg-error/10 p-4 text-sm text-error"
        >
          <AlertTriangle size={18} className="shrink-0" />
          <span>
            Could not load users.{' '}
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
          keyOf={(user) => user.id}
          isLoading={isPending}
          empty={
            <EmptyState
              icon={<UsersIcon size={22} />}
              title="No users found"
              description={
                q || status
                  ? 'No accounts match the current filters.'
                  : 'No users have registered yet.'
              }
            />
          }
          renderMobileCard={(user) => (
            <div className="rounded-xl border border-border bg-surface-1 p-4">
              <div className="flex items-start justify-between gap-3">
                <UserIdentity user={user} />
                <Pill tone={toneForStatus(user.status)}>{user.status}</Pill>
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                <div>
                  <dt>Repos</dt>
                  <dd className="text-foreground tabular-nums">{user.repo_count}</dd>
                </div>
                <div>
                  <dt>Credentials</dt>
                  <dd className="text-foreground tabular-nums">
                    {user.credential_count}
                  </dd>
                </div>
                <div>
                  <dt>Reviews</dt>
                  <dd className="text-foreground tabular-nums">{user.review_count}</dd>
                </div>
              </dl>
              <p className="mt-2 text-xs text-muted-foreground">
                Joined {formatDateTime(user.created_at)} · Last login{' '}
                {user.last_login_at ? formatDateTime(user.last_login_at) : '—'}
              </p>
            </div>
          )}
          ariaLabel="Users"
        />
      </div>

      {data && (
        <Pagination
          total={data.total}
          limit={data.limit}
          offset={data.offset}
          onChange={setOffset}
          className="mt-4"
        />
      )}
    </div>
  );
}
