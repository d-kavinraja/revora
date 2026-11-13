'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CalendarRange,
  Coins,
  FolderGit2,
  GitPullRequest,
  Hash,
  RefreshCw,
  Users,
  Wrench,
} from 'lucide-react';
import { adminApi, type AdminOverview, type NumericMetric, type ScalarMetric } from '@/lib/api';
import { SkeletonCard, SkeletonList } from '@/components/shared/skeleton';
import { formatDateTime, formatDateTimeShort } from '@/components/shared/time-ago';
import { Pill, toneForStatus } from '@/components/shared/pill';
import { AdminPage, AdminSection } from '@/components/admin/page-shell';
import {
  DistributionBar,
  KpiTile,
  RankedList,
  SegmentedControl,
  type MeterTone,
} from '@/components/admin/metrics';
import { IconButton } from '@/components/admin/controls';
import { InlineEmpty, QueryError } from '@/components/admin/states';
import {
  ProviderBadge,
  ProviderMark,
  providerDisplayName,
} from '@/components/ui/provider-brand';
import {
  FEATURE_STATUS_LABELS,
  FEATURE_STATUS_TONES,
  featureLabel,
} from '@/lib/admin-features';

const PERIOD_OPTIONS = [
  { key: '24h', label: '24 hours' },
  { key: '7d', label: '7 days' },
  { key: '30d', label: '30 days' },
] as const;

type ProviderHealthRow = AdminOverview['provider_health'][number];

function ProviderHealthList({ rows }: { rows: ProviderHealthRow[] }) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              <th
                scope="col"
                className="w-[22%] pb-2 pr-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
              >
                Provider
              </th>
              <th
                scope="col"
                className="w-[12%] pb-2 pr-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
              >
                Status
              </th>
              <th
                scope="col"
                className="w-[12%] pb-2 pr-3 text-right text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
              >
                Success
              </th>
              <th
                scope="col"
                className="w-[12%] pb-2 pr-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
              >
                Circuit
              </th>
              <th
                scope="col"
                className="w-[18%] pb-2 pr-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
              >
                Snapshot
              </th>
              <th
                scope="col"
                className="w-[24%] pb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
              >
                Last error
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/70">
            {rows.map((row) => (
              <tr key={row.provider}>
                <td className="py-3 pr-3 align-top">
                  <ProviderBadge slug={row.provider} size="sm" />
                </td>
                <td className="py-3 pr-3 align-top">
                  <Pill
                    tone={toneForStatus(row.status)}
                    dot
                    className="whitespace-nowrap"
                  >
                    {row.status}
                  </Pill>
                </td>
                <td className="admin-figure py-3 pr-3 text-right align-top">
                  {row.success_rate !== null
                    ? `${(row.success_rate * 100).toFixed(1)}%`
                    : '—'}
                </td>
                <td className="py-3 pr-3 align-top text-muted-foreground">
                  {row.circuit_state ?? '—'}
                </td>
                <td className="admin-figure py-3 pr-3 align-top text-muted-foreground">
                  {row.snapshot_at ? formatDateTime(row.snapshot_at) : '—'}
                </td>
                <td className="py-3 align-top">
                  {row.last_error ? (
                    <details className="group text-xs">
                      <summary className="cursor-pointer list-none rounded text-error/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                        <span className="underline underline-offset-2 group-open:no-underline">
                          View error
                        </span>
                        {row.last_error_at && (
                          <span className="ml-2 font-mono text-muted-foreground">
                            {formatDateTimeShort(row.last_error_at)}
                          </span>
                        )}
                      </summary>
                      <p className="mt-1 break-words font-mono text-[11px] leading-relaxed text-error/90">
                        {row.last_error}
                      </p>
                    </details>
                  ) : (
                    <span className="text-xs text-muted-foreground">None</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 md:hidden">
        {rows.map((row) => (
          <article
            key={row.provider}
            className="rounded-lg border border-border bg-surface-2/50 p-3"
          >
            <div className="flex items-center justify-between gap-3">
              <ProviderBadge slug={row.provider} size="sm" />
              <Pill tone={toneForStatus(row.status)} dot>
                {row.status}
              </Pill>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
              <div>
                <dt className="text-muted-foreground">Success rate</dt>
                <dd className="admin-figure mt-0.5 font-medium text-foreground">
                  {row.success_rate !== null
                    ? `${(row.success_rate * 100).toFixed(1)}%`
                    : '—'}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Circuit</dt>
                <dd className="mt-0.5 font-medium text-foreground">
                  {row.circuit_state ?? '—'}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Snapshot</dt>
                <dd className="admin-figure mt-0.5 font-medium text-foreground">
                  {row.snapshot_at ? formatDateTime(row.snapshot_at) : '—'}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Last error</dt>
                <dd className="mt-0.5 font-medium text-foreground">
                  {row.last_error ? 'Recorded' : 'None'}
                </dd>
              </div>
            </dl>
            {row.last_error && (
              <details className="group mt-2 text-xs">
                <summary className="cursor-pointer list-none rounded text-error/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                  <span className="underline underline-offset-2 group-open:no-underline">
                    Last error
                  </span>
                  {row.last_error_at && (
                    <span className="ml-2 font-mono text-muted-foreground">
                      {formatDateTimeShort(row.last_error_at)}
                    </span>
                  )}
                </summary>
                <p className="mt-1 break-words font-mono text-[11px] leading-relaxed text-error/90">
                  {row.last_error}
                </p>
              </details>
            )}
          </article>
        ))}
      </div>
    </>
  );
}

function formatCount(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') return value.toLocaleString();
  return value;
}

function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} ms`;
}

function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}`;
}

function metricReading(
  metric: ScalarMetric | NumericMetric,
  formatter?: (value: number | string) => string,
): { value: string; unavailable: boolean; reason: string | null } {
  if (!metric.available) {
    return {
      value: 'Not recorded',
      unavailable: true,
      reason: metric.reason,
    };
  }
  if (metric.value === null || metric.value === '') {
    return { value: 'No data', unavailable: true, reason: metric.reason };
  }
  return {
    value: formatter
      ? formatter(metric.value)
      : formatCount(metric.value as number | string),
    unavailable: false,
    reason: metric.reason,
  };
}

function statusTone(status: string): MeterTone {
  const normalized = status.toLowerCase();
  if (['completed', 'success', 'ok', 'healthy'].includes(normalized)) {
    return 'success';
  }
  if (
    ['failed', 'timed_out', 'missing', 'invalid', 'down', 'error'].includes(
      normalized,
    )
  ) {
    return 'error';
  }
  if (normalized === 'running') return 'info';
  if (
    ['pending', 'queued', 'waiting', 'partial', 'stale', 'degraded'].includes(
      normalized,
    )
  ) {
    return 'warning';
  }
  return 'muted';
}

export default function AdminOverviewPage() {
  const [period, setPeriod] = useState<string>('7d');
  const { data, isPending, isError, isFetching, dataUpdatedAt, refetch } = useQuery({
    queryKey: ['admin', 'overview', period],
    queryFn: () => adminApi.overview({ period }),
    retry: 1,
  });

  const lastLogin = data
    ? metricReading(data.last_login_at, (value) => formatDateTime(String(value)))
    : null;
  const signIns = data ? metricReading(data.signed_in_users) : null;
  const p50 = data ? metricReading(data.duration_p50_ms, (value) => formatMs(Number(value))) : null;
  const p95 = data ? metricReading(data.duration_p95_ms, (value) => formatMs(Number(value))) : null;
  const tokens = data ? metricReading(data.token_usage) : null;
  const cost = data
    ? metricReading(data.cost_totals, (value) =>
        formatUsd(typeof value === 'number' ? value : null),
      )
    : null;
  const failure = data ? metricReading(data.failure_rate) : null;

  return (
    <AdminPage
      eyebrow="Monitor"
      title="Overview"
      description="Platform-wide metrics. Unrecorded sources are marked, never guessed."
      meta={
        dataUpdatedAt ? (
          <>
            <span>
              Refreshed{' '}
              {new Date(dataUpdatedAt).toLocaleTimeString('en-US', {
                hour: 'numeric',
                minute: '2-digit',
                hour12: true,
              })}
            </span>
            <span className="hidden h-3 w-px bg-border sm:block" />
            <span className="inline-flex items-center gap-1.5">
              <CalendarRange size={13} aria-hidden="true" />
              Reporting window{' '}
              {data?.period
                ? `${formatDateTimeShort(data.period.start)} to ${formatDateTimeShort(data.period.end)}`
                : 'All time'}
            </span>
          </>
        ) : undefined
      }
      actions={
        <>
          <SegmentedControl
            ariaLabel="Time period"
            options={PERIOD_OPTIONS}
            value={period}
            onChange={setPeriod}
          />
          <IconButton label="Refresh metrics" onClick={() => refetch()}>
            <RefreshCw size={16} className={isFetching ? 'animate-spin' : ''} />
          </IconButton>
        </>
      }
    >
      {isError && !isPending && (
        <QueryError
          message="Could not load metrics."
          onRetry={() => refetch()}
        />
      )}

      {isPending ? (
        <div className="space-y-6">
          <SkeletonCard count={4} />
          <div className="grid gap-4 xl:grid-cols-2">
            <SkeletonCard count={6} />
            <SkeletonCard count={6} />
          </div>
          <SkeletonList count={1} height="h-64" />
          <div className="grid gap-4 xl:grid-cols-2">
            <SkeletonList count={4} height="h-48" />
            <SkeletonList count={4} height="h-48" />
          </div>
          <SkeletonList count={1} height="h-40" />
          <SkeletonList count={1} height="h-64" />
          <div className="grid gap-4 xl:grid-cols-2">
            <SkeletonList count={1} height="h-48" />
            <SkeletonList count={1} height="h-48" />
          </div>
        </div>
      ) : data ? (
        <>
          <section aria-label="Key metrics" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile
              label="Users total"
              value={formatCount(data.users_total)}
              sub={`+${data.users_new_in_period.toLocaleString()} in period`}
              icon={<Users size={15} />}
            />
            <KpiTile
              label="Reviews total"
              value={formatCount(data.reviews_total)}
              sub={`${data.reviews_in_period.toLocaleString()} in period`}
              icon={<GitPullRequest size={15} />}
            />
            <KpiTile
              label="Failure rate"
              value={
                failure?.unavailable
                  ? failure.value
                  : `${((data.failure_rate.value ?? 0) * 100).toFixed(1)}%`
              }
              sub={
                !failure?.unavailable && data.failure_rate.sample_size !== null
                  ? `${data.failure_rate.sample_size.toLocaleString()} latest executions`
                  : undefined
              }
              reason={failure?.reason}
              unavailable={failure?.unavailable}
              icon={<Hash size={15} />}
            />
            <KpiTile
              label="Repositories connected"
              value={formatCount(data.repos_connected)}
              icon={<FolderGit2 size={15} />}
            />
          </section>

          <div className="grid gap-4">
            <AdminSection
              title="Platform activity"
              subtitle="Accounts, sign-ins and stored credentials"
            >
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                <KpiTile
                  label="Sign-ins in period"
                  value={signIns?.value ?? '—'}
                  reason={signIns?.reason}
                  unavailable={signIns?.unavailable}
                  tone="info"
                />
                <KpiTile
                  label="Last login"
                  value={lastLogin?.value ?? '—'}
                  reason={lastLogin?.reason}
                  unavailable={lastLogin?.unavailable}
                  tone="info"
                />
                <KpiTile
                  label="Credentials total"
                  value={formatCount(data.credentials_total)}
                  sub={`${data.credentials_by_provider.length} provider${
                    data.credentials_by_provider.length === 1 ? '' : 's'
                  }`}
                  tone="info"
                />
                {Object.entries(data.active_users).map(([key, metric]) => {
                  const reading = metricReading(metric);
                  return (
                    <KpiTile
                      key={key}
                      label={`Active users (${key})`}
                      value={reading.value}
                      reason={reading.reason}
                      unavailable={reading.unavailable}
                      tone="success"
                    />
                  );
                })}
              </div>
            </AdminSection>

            <AdminSection
              title="Review reliability"
              subtitle="Execution volume, retries, latency and recorded usage"
            >
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                <KpiTile
                  label="Reviews in period"
                  value={data.reviews_in_period.toLocaleString()}
                  tone="warning"
                />
                <KpiTile
                  label="Retries in period"
                  value={formatCount(data.retries_in_period)}
                  tone="warning"
                />
                <KpiTile
                  label="Duration p50"
                  value={p50?.value ?? '—'}
                  reason={p50?.reason}
                  unavailable={p50?.unavailable}
                  tone="warning"
                />
                <KpiTile
                  label="Duration p95"
                  value={p95?.value ?? '—'}
                  reason={p95?.reason}
                  unavailable={p95?.unavailable}
                  tone="warning"
                />
                <KpiTile
                  label="Tokens in period"
                  value={tokens?.value ?? '—'}
                  reason={tokens?.reason}
                  unavailable={tokens?.unavailable}
                  icon={<Hash size={15} />}
                  tone="info"
                />
                <KpiTile
                  label="Cost in period"
                  value={cost?.value ?? '—'}
                  reason={cost?.reason}
                  unavailable={cost?.unavailable}
                  icon={<Coins size={15} />}
                  tone="info"
                />
              </div>
            </AdminSection>
          </div>

          <AdminSection
            title="Provider health"
            subtitle="Latest recorded snapshot per provider"
          >
            {data.provider_health.length === 0 ? (
              <InlineEmpty>No health checks recorded.</InlineEmpty>
            ) : (
              <ProviderHealthList rows={data.provider_health} />
            )}
          </AdminSection>

          <div className="grid gap-4 xl:grid-cols-2">
            <AdminSection
              title="Provider & model usage"
              subtitle="Reviews in period"
            >
              {data.reviews_by_provider_model.length === 0 ? (
                <InlineEmpty>No reviews in this period.</InlineEmpty>
              ) : (
                <RankedList
                  items={data.reviews_by_provider_model.map((row, i) => ({
                    key: `${row.provider ?? 'unset'}-${row.model ?? 'unset'}-${i}`,
                    label: providerDisplayName(row.provider),
                    secondary: row.model ?? 'Model not recorded',
                    value: row.count,
                    leading: <ProviderMark slug={row.provider} size="sm" />,
                  }))}
                />
              )}
            </AdminSection>

            <AdminSection
              title="Failure categories"
              subtitle="Latest executions in period"
            >
              {data.failure_categories.length === 0 ? (
                <InlineEmpty>No failures recorded in this period.</InlineEmpty>
              ) : (
                <RankedList
                  tone="error"
                  items={data.failure_categories.map((row) => ({
                    key: row.category,
                    label: row.category,
                    value: row.count,
                    tone: 'error',
                  }))}
                />
              )}
            </AdminSection>
          </div>

          <AdminSection title="Reviews by status" subtitle="All time">
            {Object.keys(data.reviews_by_status).length === 0 ? (
              <InlineEmpty>No reviews yet.</InlineEmpty>
            ) : (
              <DistributionBar
                items={Object.entries(data.reviews_by_status).map(
                  ([status, count]) => ({
                    key: status,
                    label: status,
                    value: count,
                    tone: statusTone(status),
                  }),
                )}
              />
            )}
          </AdminSection>

          <AdminSection
            title="Credentials by provider"
            subtitle="Stored credentials, validity and key state"
          >
            {data.credentials_by_provider.length === 0 ? (
              <InlineEmpty>No credentials stored.</InlineEmpty>
            ) : (
              <>
                <div className="hidden overflow-x-auto md:block">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left">
                        <th
                          scope="col"
                          className="pb-2 pr-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
                        >
                          Provider
                        </th>
                        {['Total', 'Valid', 'Invalid', 'Enabled', 'Disabled'].map(
                          (label) => (
                            <th
                              key={label}
                              scope="col"
                              className="pb-2 pr-3 text-right text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground last:pr-0"
                            >
                              {label}
                            </th>
                          ),
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/70">
                      {data.credentials_by_provider.map((row) => (
                        <tr key={row.provider}>
                          <td className="py-2.5 pr-3">
                            <ProviderBadge slug={row.provider} size="sm" />
                          </td>
                          <td className="admin-figure py-2.5 pr-3 text-right">
                            {row.total}
                          </td>
                          <td className="admin-figure py-2.5 pr-3 text-right text-success">
                            {row.valid}
                          </td>
                          <td className="admin-figure py-2.5 pr-3 text-right text-error">
                            {row.invalid}
                          </td>
                          <td className="admin-figure py-2.5 pr-3 text-right">
                            {row.enabled}
                          </td>
                          <td className="admin-figure py-2.5 text-right">
                            {row.disabled}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="grid gap-2 sm:grid-cols-2 md:hidden">
                  {data.credentials_by_provider.map((row) => (
                    <div
                      key={row.provider}
                      className="rounded-lg border border-border bg-surface-2/50 p-3"
                    >
                      <ProviderBadge slug={row.provider} size="sm" />
                      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                        {[
                          ['Total', row.total],
                          ['Valid', row.valid],
                          ['Invalid', row.invalid],
                          ['Enabled', row.enabled],
                          ['Disabled', row.disabled],
                        ].map(([label, value]) => (
                          <div key={String(label)}>
                            <dt className="text-muted-foreground">{label}</dt>
                            <dd className="admin-figure mt-0.5 font-medium text-foreground">
                              {value}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  ))}
                </div>
              </>
            )}
          </AdminSection>

          <div className="grid gap-4 xl:grid-cols-2">
            <AdminSection title="Maintenance mode">
              {data.maintenance.enabled ? (
                <div className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
                  <Wrench
                    size={18}
                    className="mt-0.5 shrink-0 text-warning"
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    <p className="font-medium text-warning">
                      {data.maintenance.title ?? 'Maintenance enabled'}
                    </p>
                    {data.maintenance.message && (
                      <p className="mt-1 leading-relaxed text-muted-foreground">
                        {data.maintenance.message}
                      </p>
                    )}
                    {data.maintenance.expected_return_at && (
                      <p className="admin-figure mt-1 text-xs text-muted-foreground">
                        Expected return:{' '}
                        {formatDateTime(data.maintenance.expected_return_at)}
                      </p>
                    )}
                  </div>
                </div>
              ) : (
                <p className="inline-flex items-center gap-2 text-sm text-success">
                  <span
                    aria-hidden="true"
                    className="inline-block h-2 w-2 rounded-full bg-success"
                  />
                  Operational — user traffic is flowing normally.
                </p>
              )}
            </AdminSection>

            <AdminSection
              title="Feature flags"
              subtitle="Source of truth for gated user features"
            >
              {Object.keys(data.features).length === 0 ? (
                <InlineEmpty>No flags defined.</InlineEmpty>
              ) : (
                <ul className="grid gap-2 sm:grid-cols-2">
                  {Object.entries(data.features).map(([key, status]) => (
                    <li
                      key={key}
                      title={featureLabel(key)}
                      className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-border bg-surface-2/50 p-2.5"
                    >
                      <div className="min-w-0">
                        <p
                          className="truncate text-sm font-medium text-foreground"
                          title={featureLabel(key)}
                        >
                          {featureLabel(key)}
                        </p>
                        <p
                          className="truncate font-mono text-[11px] text-muted-foreground"
                          title={key}
                        >
                          {key}
                        </p>
                      </div>
                      <Pill
                        tone={FEATURE_STATUS_TONES[status] ?? 'muted'}
                        dot
                        className="shrink-0"
                      >
                        {FEATURE_STATUS_LABELS[status] ?? status}
                      </Pill>
                    </li>
                  ))}
                </ul>
              )}
            </AdminSection>
          </div>
        </>
      ) : null}
    </AdminPage>
  );
}
