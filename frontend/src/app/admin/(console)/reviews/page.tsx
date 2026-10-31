'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { GitPullRequest } from 'lucide-react';
import {
  adminApi,
  type AdminReviewItem,
  type AdminReviewListParams,
} from '@/lib/api';
import { DataTable, type DataTableColumn } from '@/components/shared/data-table';
import { Pagination } from '@/components/shared/pagination';
import { EmptyState } from '@/components/shared/empty-state';
import { Pill } from '@/components/shared/pill';
import { StatusBadge } from '@/components/shared/status-badge';
import { TextFilter } from '@/components/shared/text-filter';
import { formatDateTime } from '@/components/shared/time-ago';
import { AdminPage } from '@/components/admin/page-shell';
import { FilterBar, SelectFilter } from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

const PAGE_SIZE = 25;

const STATUS_OPTIONS = [
  '',
  'pending',
  'queued',
  'running',
  'completed',
  'failed',
  'cancelled',
  'stopped',
  'timed_out',
] as const;

const PERIOD_OPTIONS = [
  { value: '', label: 'All time' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
] as const;

function isFallback(review: AdminReviewItem): boolean {
  if (!review.provider) return false;
  return (
    (review.configured_provider !== null &&
      review.configured_provider !== review.provider) ||
    (review.configured_model !== null && review.configured_model !== review.model)
  );
}

export default function AdminReviewsPage() {
  const [user, setUser] = useState('');
  const [repo, setRepo] = useState('');
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [status, setStatus] = useState<string>('');
  const [error, setError] = useState('');
  const [period, setPeriod] = useState<string>('');
  const [offset, setOffset] = useState(0);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: [
      'admin',
      'reviews',
      { user, repo, provider, model, status, error, period, offset },
    ],
    queryFn: () =>
      adminApi.reviews({
        user: user || undefined,
        repo: repo || undefined,
        provider: provider || undefined,
        model: model || undefined,
        status: status || undefined,
        error: error || undefined,
        period: (period || undefined) as AdminReviewListParams['period'],
        limit: PAGE_SIZE,
        offset,
      }),
    retry: 1,
  });

  const columns: DataTableColumn<AdminReviewItem>[] = [
    {
      key: 'pr',
      header: 'Pull request',
      render: (review) => (
        <div className="min-w-0">
          <p
            className="max-w-[360px] truncate font-medium text-foreground"
            title={`${review.repository_full_name} #${review.pr_number}`}
          >
            {review.repository_full_name} #{review.pr_number}
          </p>
          <p
            className="max-w-[360px] truncate text-xs text-muted-foreground"
            title={review.pr_title}
          >
            {review.pr_title}
          </p>
        </div>
      ),
    },
    {
      key: 'owner',
      header: 'Owner',
      className: 'whitespace-nowrap',
      render: (review) => (
        <span
          className="max-w-[260px] truncate text-muted-foreground"
          title={review.owner_email}
        >
          {review.owner_email}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (review) => <StatusBadge status={review.status} />,
    },
    {
      key: 'configured',
      header: 'Configured',
      render: (review) => (
        <span
          className="block max-w-[260px] truncate text-xs text-foreground/80"
          title={
            review.configured_provider || review.configured_model
              ? `${review.configured_provider ?? 'Unset'}${review.configured_model ? ` · ${review.configured_model}` : ''}`
              : 'Not configured'
          }
        >
          {review.configured_provider || review.configured_model ? (
            <>
              {review.configured_provider ?? 'Unset'}
              {review.configured_model ? ` · ${review.configured_model}` : ''}
            </>
          ) : (
            <span className="text-muted-foreground">Not configured</span>
          )}
        </span>
      ),
    },
    {
      key: 'actual',
      header: 'Actual execution',
      render: (review) => (
        <div className="min-w-0 max-w-[240px] text-xs">
          <div className="flex min-w-0 items-center gap-2">
            <span
              className="max-w-[200px] truncate text-foreground/80"
              title={
                review.provider || review.model
                  ? [review.provider, review.model].filter(Boolean).join(' · ')
                  : 'Not recorded'
              }
            >
              {review.provider || review.model
                ? [review.provider, review.model].filter(Boolean).join(' · ')
                : 'Not recorded'}
            </span>
            {isFallback(review) && (
              <Pill tone="warning" dot>
                fallback
              </Pill>
            )}
          </div>
          <p className="text-muted-foreground">
            {[
              review.execution_status,
              review.duration_ms !== null
                ? `${review.duration_ms.toLocaleString()} ms`
                : null,
            ]
              .filter(Boolean)
              .join(' · ') || '—'}
          </p>
        </div>
      ),
    },
    {
      key: 'error',
      header: 'Error',
      render: (review) =>
        review.error ? (
          <span className="block max-w-[260px] truncate text-error" title={review.error}>
            {review.error}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: 'created',
      header: 'Created',
      className: 'whitespace-nowrap',
      render: (review) => (
        <span className="admin-figure whitespace-nowrap text-muted-foreground">
          {formatDateTime(review.created_at)}
        </span>
      ),
    },
  ];

  return (
    <AdminPage
      eyebrow="Monitor"
      title="Reviews"
      description={
        data
          ? `${data.total.toLocaleString()} review${data.total === 1 ? '' : 's'}`
          : 'Configured mappings vs. actual executions.'
      }
    >
      <FilterBar label="Review filters">
        <TextFilter
          value={user}
          onChange={(value) => {
            setUser(value);
            setOffset(0);
          }}
          placeholder="Owner email or GitHub…"
          ariaLabel="Filter by owner"
          className="w-full sm:w-52"
        />
        <TextFilter
          value={repo}
          onChange={(value) => {
            setRepo(value);
            setOffset(0);
          }}
          placeholder="Repository…"
          ariaLabel="Filter by repository"
          className="w-full sm:w-44"
        />
        <TextFilter
          value={provider}
          onChange={(value) => {
            setProvider(value);
            setOffset(0);
          }}
          placeholder="Provider…"
          ariaLabel="Filter by provider"
          className="w-full sm:w-40"
        />
        <TextFilter
          value={model}
          onChange={(value) => {
            setModel(value);
            setOffset(0);
          }}
          placeholder="Model…"
          ariaLabel="Filter by model"
          className="w-full sm:w-40"
        />
        <SelectFilter
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter by status"
          className="w-full sm:w-40"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.filter(Boolean).map((option) => (
            <option key={option} value={option}>
              {option.charAt(0).toUpperCase() + option.slice(1).replace('_', ' ')}
            </option>
          ))}
        </SelectFilter>
        <TextFilter
          value={error}
          onChange={(value) => {
            setError(value);
            setOffset(0);
          }}
          placeholder="Error text…"
          ariaLabel="Filter by error"
          className="w-full sm:w-44"
        />
        <SelectFilter
          value={period}
          onChange={(event) => {
            setPeriod(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter by period"
          className="w-full sm:w-44"
        >
          {PERIOD_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectFilter>
      </FilterBar>

      {isError && !isPending && (
        <QueryError message="Could not load reviews." onRetry={() => refetch()} />
      )}

      <DataTable
        columns={columns}
        rows={data?.items ?? []}
        keyOf={(review) => review.id}
        isLoading={isPending}
        empty={
          <EmptyState
            icon={<GitPullRequest size={22} />}
            title="No reviews found"
            description={
              user || repo || provider || model || status || error || period
                ? 'No reviews match the current filters.'
                : 'No reviews have been created yet.'
            }
          />
        }
        renderMobileCard={(review) => (
          <div className="rounded-xl border border-border bg-surface-1 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-medium text-foreground">
                  {review.repository_full_name} #{review.pr_number}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {review.owner_email}
                </p>
              </div>
              <StatusBadge status={review.status} />
            </div>
            <div className="mt-3 space-y-1 text-xs">
              <p className="text-muted-foreground">
                Configured:{' '}
                <span className="text-foreground/80">
                  {review.configured_provider
                    ? `${review.configured_provider}${review.configured_model ? ` · ${review.configured_model}` : ''}`
                    : 'Not configured'}
                </span>
              </p>
              <p className="text-muted-foreground">
                Executed:{' '}
                <span className="text-foreground/80">
                  {review.provider
                    ? `${review.provider}${review.model ? ` · ${review.model}` : ''}`
                    : 'Not recorded'}
                </span>{' '}
                {isFallback(review) && (
                  <Pill tone="warning" dot>
                    fallback
                  </Pill>
                )}
              </p>
              {review.error && <p className="text-error">{review.error}</p>}
              <p className="admin-figure text-muted-foreground">
                {formatDateTime(review.created_at)}
              </p>
            </div>
          </div>
        )}
        ariaLabel="Reviews"
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
