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
import { ProviderBadge } from '@/components/ui/provider-brand';
import { modelSelectionView } from '@/lib/review-model-selection';
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
  return review.selection_source === 'routing_fallback';
}

function humanize(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
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
      header: 'Repository mapping',
      render: (review) => (
        <div className="min-w-0 max-w-[240px] text-xs">
          <span className="block text-[11px] uppercase tracking-wide text-muted-foreground">
            {review.repository_mapping_status === 'mapped'
              ? 'Mapped'
              : review.repository_mapping_status === 'not_mapped'
                ? 'Not mapped'
                : 'Unknown'}
          </span>
          {review.repository_provider ? (
            <div className="mt-0.5 min-w-0">
              <ProviderBadge
                slug={review.repository_provider}
                size="sm"
                muted
                className="max-w-40"
              />
              {review.repository_model && (
                <p className="truncate text-muted-foreground">
                  {review.repository_model}
                </p>
              )}
            </div>
          ) : (
            <span className="mt-0.5 block text-muted-foreground">
              {review.repository_mapping_status === 'not_mapped'
                ? 'Not mapped'
                : 'Not recorded'}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'selected',
      header: 'Resolved selection',
      render: (review) => {
        const view = modelSelectionView(review);
        return (
          <div className="min-w-0 max-w-[240px] text-xs">
            <div className="flex min-w-0 items-center gap-1.5">
              {view.hasSelection ? (
                <ProviderBadge
                  slug={view.providerSlug}
                  label={view.providerLabel}
                  size="sm"
                  className="max-w-40"
                />
              ) : (
                <span className="truncate text-muted-foreground">
                  No model resolved
                </span>
              )}
              {isFallback(review) && (
                <Pill tone="warning" dot>
                  routing
                </Pill>
              )}
            </div>
            {view.model && (
              <p className="mt-0.5 truncate text-muted-foreground">
                {view.model}
              </p>
            )}
            <p className="text-muted-foreground">{view.sourceLabel}</p>
          </div>
        );
      },
    },
    {
      key: 'actual',
      header: 'Actual execution',
      render: (review) => {
        const view = modelSelectionView(review);
        return (
          <div className="min-w-0 max-w-[240px] text-xs">
            {view.executed && view.actualProvider ? (
              <div className="min-w-0">
                <ProviderBadge
                  slug={view.actualProvider}
                  label={view.actualProvider}
                  size="sm"
                  muted
                  className="max-w-40"
                />
                {view.actualModel && (
                  <p className="mt-0.5 truncate text-muted-foreground">
                    {view.actualModel}
                  </p>
                )}
              </div>
            ) : (
              <span className="text-muted-foreground">{view.actualLabel}</span>
            )}
            <p className="mt-0.5 text-muted-foreground">
              {[
                review.execution_status
                  ? humanize(review.execution_status)
                  : null,
                review.duration_ms !== null
                  ? `${review.duration_ms.toLocaleString()} ms`
                  : null,
              ]
                .filter(Boolean)
                .join(' · ') || '—'}
            </p>
          </div>
        );
      },
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
              {humanize(option)}
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
            <div className="mt-3 space-y-2 text-xs">
              <div>
                <p className="text-muted-foreground">Configured</p>
                {review.configured_provider ? (
                  <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-2">
                    <ProviderBadge
                      slug={review.configured_provider}
                      size="sm"
                      muted
                      className="max-w-40"
                    />
                    {review.configured_model && (
                      <span className="min-w-0 truncate text-muted-foreground">
                        {review.configured_model}
                      </span>
                    )}
                  </div>
                ) : (
                  <p className="mt-0.5 text-foreground/80">Not configured</p>
                )}
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-muted-foreground">Executed</p>
                  {isFallback(review) && (
                    <Pill tone="warning" dot>
                      fallback
                    </Pill>
                  )}
                </div>
                {review.provider ? (
                  <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-2">
                    <ProviderBadge
                      slug={review.provider}
                      size="sm"
                      muted
                      className="max-w-40"
                    />
                    {review.model && (
                      <span className="min-w-0 truncate text-muted-foreground">
                        {review.model}
                      </span>
                    )}
                  </div>
                ) : (
                  <p className="mt-0.5 text-foreground/80">Not recorded</p>
                )}
              </div>
              {review.error && (
                <p className="break-words text-error">{review.error}</p>
              )}
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
