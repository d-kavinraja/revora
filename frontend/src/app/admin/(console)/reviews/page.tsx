'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, GitPullRequest } from 'lucide-react';
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
            className="font-medium text-foreground truncate max-w-[360px]"
            title={`${review.repository_full_name} #${review.pr_number}`}
          >
            {review.repository_full_name} #{review.pr_number}
          </p>
          <p className="max-w-[360px] truncate text-xs text-muted-foreground" title={review.pr_title}>
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
        <span className="text-muted-foreground truncate max-w-[260px]" title={review.owner_email}>{review.owner_email}</span>
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
          className="block text-xs text-foreground/80 truncate max-w-[260px]"
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
        <div className="text-xs min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className="text-foreground/80 truncate"
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
            {isFallback(review) && <Pill tone="warning">fallback</Pill>}
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
          <span
            className="block max-w-[260px] truncate text-error"
            title={review.error}
          >
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
        <span className="text-muted-foreground whitespace-nowrap">
          {formatDateTime(review.created_at)}
        </span>
      ),
    },
  ];

  const filterCls =
    'w-full min-w-0 h-11 rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';

  return (
    <div>
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
          Reviews
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {data
            ? `${data.total.toLocaleString()} review${data.total === 1 ? '' : 's'}`
            : 'Configured mappings vs. actual executions.'}
        </p>
      </div>

      <div className="mt-4 grid min-w-0 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <TextFilter
          value={user}
          onChange={(value) => {
            setUser(value);
            setOffset(0);
          }}
          placeholder="Owner email or GitHub…"
          ariaLabel="Filter by owner"
        />
        <TextFilter
          value={repo}
          onChange={(value) => {
            setRepo(value);
            setOffset(0);
          }}
          placeholder="Repository…"
          ariaLabel="Filter by repository"
        />
        <TextFilter
          value={provider}
          onChange={(value) => {
            setProvider(value);
            setOffset(0);
          }}
          placeholder="Provider…"
          ariaLabel="Filter by provider"
        />
        <TextFilter
          value={model}
          onChange={(value) => {
            setModel(value);
            setOffset(0);
          }}
          placeholder="Model…"
          ariaLabel="Filter by model"
        />
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter by status"
          className={filterCls}
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.filter(Boolean).map((option) => (
            <option key={option} value={option}>
              {option.charAt(0).toUpperCase() + option.slice(1).replace('_', ' ')}
            </option>
          ))}
        </select>
        <TextFilter
          value={error}
          onChange={(value) => {
            setError(value);
            setOffset(0);
          }}
          placeholder="Error text…"
          ariaLabel="Filter by error"
        />
        <select
          value={period}
          onChange={(event) => {
            setPeriod(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter by period"
          className={filterCls}
        >
          {PERIOD_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {isError && !isPending && (
        <div
          role="alert"
          className="mt-4 flex items-center gap-3 rounded-xl border border-error/40 bg-error/10 p-4 text-sm text-error"
        >
          <AlertTriangle size={18} className="shrink-0" />
          <span>
            Could not load reviews.{' '}
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
                  <p className="font-medium text-foreground truncate">
                    {review.repository_full_name} #{review.pr_number}
                  </p>
                  <p className="text-xs text-muted-foreground truncate">
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
                  {isFallback(review) && <Pill tone="warning">fallback</Pill>}
                </p>
                {review.error && <p className="text-error">{review.error}</p>}
                <p className="text-muted-foreground">
                  {formatDateTime(review.created_at)}
                </p>
              </div>
            </div>
          )}
          ariaLabel="Reviews"
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
