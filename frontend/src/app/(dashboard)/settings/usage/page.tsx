'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Coins, Hash, Zap } from 'lucide-react';
import { api, type UsageRecord, type UsageSummary } from '@/lib/api';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { UsageChart } from '@/components/usage/usage-chart';
import { KpiTile, RankedList, StatGroup } from '@/components/admin/metrics';
import { AdminLoading, QueryError } from '@/components/admin/states';
import { formatDateTime } from '@/components/shared/time-ago';

const PERIODS = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: '7 days' },
  { key: 'month', label: '30 days' },
] as const;

function money(value: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

export default function UsagePage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'usage');

  const { data: analyticsStatus } = useQuery({
    queryKey: ['platform', 'usage-analytics'],
    queryFn: api.getUsageAnalyticsStatus,
    enabled: typeof window !== 'undefined',
    retry: 1,
  });

  const [period, setPeriod] = useState<string>('month');

  const summaryQuery = useQuery({
    queryKey: ['usage', 'summary', period],
    queryFn: () => api.getUsageSummary(period),
    enabled: typeof window !== 'undefined' && status === 'enabled',
    retry: 1,
  });

  const trendQuery = useQuery({
    queryKey: ['usage', 'trend'],
    queryFn: () => api.getUsageTrend(30),
    enabled: typeof window !== 'undefined' && status === 'enabled',
    retry: 1,
  });

  const recordsQuery = useQuery({
    queryKey: ['usage', 'records'],
    queryFn: () => api.getUsageRecords(20, 0),
    enabled: typeof window !== 'undefined' && status === 'enabled',
    retry: 1,
  });

  if (status !== 'enabled') {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable status={status} message={message} title="Usage is unavailable" variant="page" />
      </div>
    );
  }

  const summary: UsageSummary | undefined = summaryQuery.data;
  const trend = trendQuery.data ?? [];
  const records: UsageRecord[] = recordsQuery.data ?? [];

  const providerItems = Object.entries(summary?.by_provider ?? {}).map(([key, value]) => ({
    key,
    label: key,
    value: Math.round(value * 10000) / 10000,
    tone: 'brand' as const,
  }));

  const modelItems = Object.entries(summary?.by_model ?? {}).map(([key, value]) => ({
    key,
    label: key,
    value: Math.round(value * 10000) / 10000,
    tone: 'info' as const,
  }));

  const featureItems = Object.entries(summary?.by_feature ?? {}).map(([key, value]) => ({
    key,
    label: key,
    value: Math.round(value * 10000) / 10000,
    tone: 'success' as const,
  }));

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Usage & Costs</h1>
          <p className="text-sm text-muted-foreground">Token consumption, cost and request activity from recorded usage.</p>
        </div>
        <div className="flex gap-2">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                period === p.key
                  ? 'border-brand bg-brand/10 text-brand'
                  : 'border-border text-foreground/70 hover:bg-surface-2'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {analyticsStatus && !analyticsStatus.enabled && (
        <div className="rounded-lg border border-border bg-surface-1 p-4 text-sm text-muted-foreground">
          Optional usage analytics collection is currently disabled by an administrator. Historical usage data remains available.
        </div>
      )}

      {summaryQuery.isError && <QueryError message="Could not load usage summary." onRetry={() => summaryQuery.refetch()} />}

      {summaryQuery.isPending && <AdminLoading label="Loading usage…" />}

      {summary && (
        <StatGroup label="Overview" columns={4}>
          <KpiTile label="Requests" value={summary.request_count.toLocaleString()} icon={<Zap size={16} />} />
          <KpiTile label="Total tokens" value={summary.total_tokens.toLocaleString()} icon={<Hash size={16} />} />
          <KpiTile label="Input tokens" value={summary.input_tokens.toLocaleString()} />
          <KpiTile label="Output tokens" value={summary.output_tokens.toLocaleString()} />
          <KpiTile label="Total cost" value={money(summary.total_cost_usd)} icon={<Coins size={16} />} tone="success" />
        </StatGroup>
      )}

      <UsageChart data={trend} isLoading={trendQuery.isPending} />

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-3">By provider (cost)</h2>
          {providerItems.length ? <RankedList items={providerItems} /> : <p className="text-sm text-muted-foreground">No data.</p>}
        </section>
        <section className="rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-3">By model (cost)</h2>
          {modelItems.length ? <RankedList items={modelItems} /> : <p className="text-sm text-muted-foreground">No data.</p>}
        </section>
        <section className="rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-3">By feature (cost)</h2>
          {featureItems.length ? <RankedList items={featureItems} /> : <p className="text-sm text-muted-foreground">No data.</p>}
        </section>
      </div>

      <section className="rounded-xl border border-border bg-surface-1 p-5">
        <h2 className="text-sm font-semibold text-foreground mb-3">Recent requests</h2>
        {recordsQuery.isPending && <AdminLoading label="Loading records…" />}
        {records.length === 0 && !recordsQuery.isPending && (
          <p className="text-sm text-muted-foreground">No recorded requests for this period.</p>
        )}
        {records.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="text-left py-2">When</th>
                  <th className="text-left py-2">Provider</th>
                  <th className="text-left py-2">Model</th>
                  <th className="text-left py-2">Feature</th>
                  <th className="text-right py-2">Tokens</th>
                  <th className="text-right py-2">Cost</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr key={r.id} className="border-t border-border">
                    <td className="py-2 text-muted-foreground">{formatDateTime(r.created_at)}</td>
                    <td className="py-2">{r.provider}</td>
                    <td className="py-2">{r.model}</td>
                    <td className="py-2">{r.feature}</td>
                    <td className="py-2 text-right">{(r.input_tokens + r.output_tokens).toLocaleString()}</td>
                    <td className="py-2 text-right">{money(r.total_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
