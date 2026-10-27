'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Coins,
  Hash,
  RefreshCw,
  Wrench,
} from 'lucide-react';
import { adminApi, type NumericMetric, type ScalarMetric } from '@/lib/api';
import { SkeletonCard, SkeletonList } from '@/components/shared/skeleton';
import { formatDateTime } from '@/components/shared/time-ago';

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

function MetricTile({
  label,
  metric,
  value,
  sub,
}: {
  label: string;
  metric?: ScalarMetric | NumericMetric;
  value?: string;
  sub?: string;
}) {
  const valueText =
    metric && !metric.available
      ? 'Not recorded'
      : metric && metric.value === null
        ? 'No data'
        : value ?? (metric ? formatCount(metric.value) : '—');
  return (
    <section className="rounded-xl border border-border bg-surface-1 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p
        className={`mt-2 text-2xl font-semibold tracking-tight ${
          metric && !metric.available ? 'text-muted-foreground' : 'text-foreground'
        }`}
      >
        {valueText}
      </p>
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      {metric && !metric.available && metric.reason && (
        <p className="mt-1 text-xs text-muted-foreground italic">
          {metric.reason}
        </p>
      )}
    </section>
  );
}

function SectionCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface-1 p-5">
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      {subtitle && (
        <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
      )}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function StatusDot({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const cls = normalized.includes('ok')
    ? 'bg-success'
    : normalized.includes('stale')
      ? 'bg-warning'
      : normalized.includes('missing') || normalized.includes('down')
        ? 'bg-error'
        : 'bg-muted-foreground';
  return <span className={`inline-block w-2 h-2 rounded-full ${cls}`} />;
}

export default function AdminOverviewPage() {
  const [period, setPeriod] = useState<string>('7d');
  const {
    data,
    isPending,
    isError,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['admin', 'overview', period],
    queryFn: () => adminApi.overview({ period }),
    retry: 1,
  });

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
            Overview
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Platform-wide metrics. Unrecorded sources are marked, never guessed.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div
            role="group"
            aria-label="Time period"
            className="flex items-center rounded-lg border border-border bg-surface-1 p-1"
          >
            {PERIOD_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setPeriod(option.key)}
                aria-pressed={period === option.key}
                className={`h-9 px-3 rounded-md text-sm font-medium transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                  period === option.key
                    ? 'bg-brand/10 text-brand'
                    : 'text-foreground/70 hover:text-foreground hover:bg-surface-2'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            aria-label="Refresh metrics"
            className="h-11 w-11 inline-flex items-center justify-center rounded-lg border border-border text-foreground/70 hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <RefreshCw size={16} className={isFetching ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {isError && !isPending && (
        <div
          role="alert"
          className="mt-6 flex items-start gap-3 rounded-xl border border-error/40 bg-error/10 p-4 text-sm text-error"
        >
          <AlertTriangle size={18} className="mt-0.5 shrink-0" />
          <div>
            <p className="font-medium">Could not load metrics.</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-1 underline underline-offset-2 cursor-pointer"
            >
              Try again
            </button>
          </div>
        </div>
      )}

      {isPending ? (
        <div className="mt-6 space-y-6">
          <SkeletonCard count={8} />
          <SkeletonList count={3} height="h-28" />
        </div>
      ) : data ? (
        <>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricTile
              label="Users total"
              value={formatCount(data.users_total)}
              sub={`+${data.users_new_in_period.toLocaleString()} in period`}
            />
            <MetricTile label="Sign-ins in period" metric={data.signed_in_users} />
            <MetricTile
              label="Last login"
              metric={data.last_login_at}
              value={
                typeof data.last_login_at.value === 'string'
                  ? formatDateTime(data.last_login_at.value)
                  : undefined
              }
            />
            <MetricTile
              label="Credentials total"
              value={formatCount(data.credentials_total)}
              sub={`${data.credentials_by_provider.length} provider${
                data.credentials_by_provider.length === 1 ? '' : 's'
              }`}
            />
            <MetricTile
              label="Repositories connected"
              value={formatCount(data.repos_connected)}
            />
            <MetricTile
              label="Reviews total"
              value={formatCount(data.reviews_total)}
              sub={`${data.reviews_in_period.toLocaleString()} in period`}
            />
            <MetricTile
              label="Retries in period"
              value={formatCount(data.retries_in_period)}
            />
            <MetricTile
              label="Failure rate"
              metric={data.failure_rate}
              value={
                data.failure_rate.value !== null
                  ? `${(data.failure_rate.value * 100).toFixed(1)}%`
                  : undefined
              }
              sub={
                data.failure_rate.sample_size !== null
                  ? `${data.failure_rate.sample_size.toLocaleString()} latest executions`
                  : undefined
              }
            />
            <MetricTile
              label="Duration p50"
              metric={data.duration_p50_ms}
              value={formatMs(data.duration_p50_ms.value)}
            />
            <MetricTile
              label="Duration p95"
              metric={data.duration_p95_ms}
              value={formatMs(data.duration_p95_ms.value)}
            />
            <MetricTile
              label="Tokens in period"
              metric={data.token_usage}
              value={formatCount(data.token_usage.value)}
            />
            <MetricTile
              label="Cost in period"
              metric={data.cost_totals}
              value={formatUsd(
                typeof data.cost_totals.value === 'number'
                  ? data.cost_totals.value
                  : null,
              )}
            />
          </div>

          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(data.active_users).map(([key, metric]) => (
              <MetricTile key={key} label={`Active users (${key})`} metric={metric} />
            ))}
          </div>

          <div className="mt-6 grid gap-4 lg:grid-cols-2">
            <SectionCard title="Reviews by status" subtitle="All time">
              {Object.keys(data.reviews_by_status).length === 0 ? (
                <p className="text-sm text-muted-foreground">No reviews yet.</p>
              ) : (
                <ul className="flex flex-wrap gap-2">
                  {Object.entries(data.reviews_by_status).map(([status, count]) => (
                    <li
                      key={status}
                      className="inline-flex items-center gap-2 rounded-full border border-border bg-surface-2 px-3 py-1.5 text-sm"
                    >
                      <StatusDot status={status} />
                      <span className="text-foreground/80 capitalize">{status}</span>
                      <span className="font-semibold text-foreground">
                        {count.toLocaleString()}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>

            <SectionCard
              title="Provider & model usage"
              subtitle="Reviews in period"
            >
              {data.reviews_by_provider_model.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No reviews in this period.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.reviews_by_provider_model.map((row, i) => (
                    <li
                      key={`${row.provider ?? 'unset'}-${row.model ?? 'unset'}-${i}`}
                      className="flex items-center justify-between gap-3 text-sm"
                    >
                      <span className="text-foreground/80 truncate">
                        {row.provider ?? 'Unset'}
                        <span className="text-muted-foreground">
                          {' · '}
                          {row.model ?? 'Unset'}
                        </span>
                      </span>
                      <span className="font-semibold text-foreground">
                        {row.count.toLocaleString()}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>

            <SectionCard title="Failure categories" subtitle="Latest executions in period">
              {data.failure_categories.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No failures recorded in this period.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.failure_categories.map((row) => (
                    <li
                      key={row.category}
                      className="flex items-center justify-between gap-3 text-sm"
                    >
                      <span className="text-foreground/80">{row.category}</span>
                      <span className="font-semibold text-foreground">
                        {row.count.toLocaleString()}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>

            <SectionCard title="Credentials by provider">
              {data.credentials_by_provider.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No credentials stored.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <tr>
                        <th scope="col" className="py-2 pr-3 font-medium">Provider</th>
                        <th scope="col" className="py-2 pr-3 font-medium">Total</th>
                        <th scope="col" className="py-2 pr-3 font-medium">Valid</th>
                        <th scope="col" className="py-2 pr-3 font-medium">Invalid</th>
                        <th scope="col" className="py-2 pr-3 font-medium">Enabled</th>
                        <th scope="col" className="py-2 font-medium">Disabled</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {data.credentials_by_provider.map((row) => (
                        <tr key={row.provider}>
                          <td className="py-2 pr-3 text-foreground/90">{row.provider}</td>
                          <td className="py-2 pr-3">{row.total}</td>
                          <td className="py-2 pr-3 text-success">{row.valid}</td>
                          <td className="py-2 pr-3 text-error">{row.invalid}</td>
                          <td className="py-2 pr-3">{row.enabled}</td>
                          <td className="py-2">{row.disabled}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>
          </div>

          <div className="mt-6 grid gap-4 lg:grid-cols-2">
            <SectionCard
              title="Provider health"
              subtitle="Latest recorded snapshot per provider"
            >
              {data.provider_health.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No health checks recorded.
                </p>
              ) : (
                <ul className="space-y-3">
                  {data.provider_health.map((row) => (
                    <li
                      key={row.provider}
                      className="rounded-lg border border-border bg-surface-2/50 p-3 text-sm"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="inline-flex items-center gap-2 font-medium text-foreground">
                          <StatusDot status={row.status} />
                          {row.provider}
                        </span>
                        <span className="text-muted-foreground capitalize">
                          {row.status}
                          {row.circuit_state ? ` · circuit ${row.circuit_state}` : ''}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                        <span>
                          Success rate{' '}
                          {row.success_rate !== null
                            ? `${(row.success_rate * 100).toFixed(1)}%`
                            : '—'}
                        </span>
                        <span>
                          {row.snapshot_at ? formatDateTime(row.snapshot_at) : '—'}
                        </span>
                      </div>
                      {row.last_error && (
                        <p className="mt-1 truncate text-xs text-error" title={row.last_error}>
                          {row.last_error}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>

            <div className="space-y-4">
              <SectionCard title="Maintenance mode">
                {data.maintenance.enabled ? (
                  <div className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
                    <Wrench size={18} className="mt-0.5 shrink-0 text-warning" />
                    <div>
                      <p className="font-medium text-warning">
                        {data.maintenance.title ?? 'Maintenance enabled'}
                      </p>
                      {data.maintenance.message && (
                        <p className="mt-1 text-muted-foreground">
                          {data.maintenance.message}
                        </p>
                      )}
                      {data.maintenance.expected_return_at && (
                        <p className="mt-1 text-xs text-muted-foreground">
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
              </SectionCard>

              <SectionCard
                title="Feature flags"
                subtitle="Source of truth for gated user features"
              >
                {Object.keys(data.features).length === 0 ? (
                  <p className="text-sm text-muted-foreground">No flags defined.</p>
                ) : (
                  <ul className="flex flex-wrap gap-2">
                    {Object.entries(data.features).map(([key, status]) => (
                      <li
                        key={key}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
                          status === 'enabled'
                            ? 'border-success/30 bg-success/10 text-success'
                            : 'border-border bg-surface-2 text-muted-foreground'
                        }`}
                      >
                        <Hash size={11} />
                        {key}
                        <span className="uppercase tracking-wide">{status}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </SectionCard>

              <SectionCard title="Recorded period">
                <p className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                  <Coins size={15} />
                  {formatDateTime(data.period.start)} → {formatDateTime(data.period.end)}
                </p>
              </SectionCard>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
