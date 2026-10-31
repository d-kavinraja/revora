'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Coins,
  FolderGit2,
  GitPullRequest,
  Hash,
  RefreshCw,
  Users,
  Wrench,
} from 'lucide-react';
import { adminApi, type NumericMetric, type ScalarMetric } from '@/lib/api';
import { SkeletonCard, SkeletonList } from '@/components/shared/skeleton';
import { formatDateTime } from '@/components/shared/time-ago';
import { AdminPage, AdminSection } from '@/components/admin/page-shell';
import {
  DistributionBar,
  KpiTile,
  RankedList,
  SegmentedControl,
  StatGroup,
  type MeterTone,
} from '@/components/admin/metrics';
import { IconButton } from '@/components/admin/controls';
import { InlineEmpty, QueryError } from '@/components/admin/states';

const PERIOD_OPTIONS = [
  { key: '24h', label: '24 hours' },
  { key: '7d', label: '7 days' },
  { key: '30d', label: '30 days' },
] as const;

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

function StatusDot({ status }: { status: string }) {
  const tone = statusTone(status);
  const cls =
    tone === 'success'
      ? 'bg-success'
      : tone === 'warning'
        ? 'bg-warning'
        : tone === 'error'
          ? 'bg-error'
          : tone === 'info'
            ? 'bg-info'
            : 'bg-muted-foreground';
  return (
    <span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full ${cls}`} />
  );
}

export default function AdminOverviewPage() {
  const [period, setPeriod] = useState<string>('7d');
  const { data, isPending, isError, isFetching, refetch } = useQuery({
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
          <SkeletonCard count={7} />
          <SkeletonList count={3} height="h-40" />
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

          <StatGroup
            label="Platform"
            description="Accounts and stored credentials"
            columns={3}
          >
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
          </StatGroup>

          <StatGroup
            label="Active users"
            description="Distinct users with activity in each window"
            columns={3}
          >
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
          </StatGroup>

          <StatGroup
            label="Reviews & reliability"
            description="Execution volume, retries and latency"
            columns={4}
          >
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
          </StatGroup>

          <StatGroup
            label="Usage & cost"
            description="Recorded usage analytics"
            columns={2}
          >
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
          </StatGroup>

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

          <div className="admin-masonry">
            <AdminSection
              title="Provider health"
              subtitle="Latest recorded snapshot per provider"
            >
              {data.provider_health.length === 0 ? (
                <InlineEmpty>No health checks recorded.</InlineEmpty>
              ) : (
                <ul className="space-y-2">
                  {data.provider_health.map((row) => (
                    <li
                      key={row.provider}
                      className="rounded-lg border border-border bg-surface-2/50 p-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="inline-flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
                          <StatusDot status={row.status} />
                          <span className="truncate">{row.provider}</span>
                        </span>
                        <span className="shrink-0 text-xs capitalize text-muted-foreground">
                          {row.status}
                          {row.circuit_state
                            ? ` · circuit ${row.circuit_state}`
                            : ''}
                        </span>
                      </div>
                      <div className="mt-1.5 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                        <span className="admin-figure">
                          Success rate{' '}
                          {row.success_rate !== null
                            ? `${(row.success_rate * 100).toFixed(1)}%`
                            : '—'}
                        </span>
                        <span className="admin-figure">
                          {row.snapshot_at ? formatDateTime(row.snapshot_at) : '—'}
                        </span>
                      </div>
                      {row.last_error && (
                        <p
                          className="mt-1 truncate text-xs text-error"
                          title={row.last_error}
                        >
                          {row.last_error}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </AdminSection>

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
                    label: row.provider ?? 'Unset',
                    secondary: row.model ?? 'Unset',
                    value: row.count,
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

            <AdminSection title="Credentials by provider">
              {data.credentials_by_provider.length === 0 ? (
                <InlineEmpty>No credentials stored.</InlineEmpty>
              ) : (
                <div className="overflow-x-auto">
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
                          <td className="py-2 pr-3 text-foreground/90">
                            {row.provider}
                          </td>
                          <td className="admin-figure py-2 pr-3 text-right">
                            {row.total}
                          </td>
                          <td className="admin-figure py-2 pr-3 text-right text-success">
                            {row.valid}
                          </td>
                          <td className="admin-figure py-2 pr-3 text-right text-error">
                            {row.invalid}
                          </td>
                          <td className="admin-figure py-2 pr-3 text-right">
                            {row.enabled}
                          </td>
                          <td className="admin-figure py-2 text-right">
                            {row.disabled}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </AdminSection>

            <AdminSection title="Maintenance mode">
              {data.maintenance.enabled ? (
                <div className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
                  <Wrench size={18} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
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
                        Expected return: {data.maintenance.expected_return_at}
                      </p>
                    )}
                  </div>
                </div>
              ) : (
                <p className="inline-flex items-center gap-2 text-sm text-success">
                  <StatusDot status="ok" />
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
                <ul className="flex flex-wrap gap-2">
                  {Object.entries(data.features).map(([key, status]) => (
                    <li
                      key={key}
                      className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium ${
                        status === 'enabled'
                          ? 'border-success/30 bg-success/10 text-success'
                          : 'border-border bg-surface-2 text-muted-foreground'
                      }`}
                    >
                      <Hash size={11} aria-hidden="true" />
                      <span className="font-mono">{key}</span>
                      <span className="uppercase tracking-[0.06em]">{status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </AdminSection>

            <AdminSection title="Recorded period">
              <p className="admin-figure inline-flex items-center gap-2 text-sm text-muted-foreground">
                <Coins size={15} aria-hidden="true" />
                {formatDateTime(data.period.start)} → {formatDateTime(data.period.end)}
              </p>
            </AdminSection>
          </div>
        </>
      ) : null}
    </AdminPage>
  );
}
