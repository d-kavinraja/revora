'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, Clock, Hash, Layers } from 'lucide-react';
import { api } from '@/lib/api';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { UsageChart } from '@/components/usage/usage-chart';
import { KpiTile, RankedList, StatGroup } from '@/components/admin/metrics';
import { AdminLoading, QueryError } from '@/components/admin/states';

export default function AnalyticsPage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'analytics');

  const { data: analyticsStatus } = useQuery({
    queryKey: ['platform', 'usage-analytics'],
    queryFn: api.getUsageAnalyticsStatus,
    retry: 1,
  });

  const [days] = useState(30);

  const requestsQuery = useQuery({
    queryKey: ['analytics', 'requests'],
    queryFn: () => api.getRequestLogs(200, 0),
    enabled: status === 'enabled',
    retry: 1,
  });

  const errorsQuery = useQuery({
    queryKey: ['analytics', 'errors'],
    queryFn: () => api.getErrorSummary(),
    enabled: status === 'enabled',
    retry: 1,
  });

  const latencyQuery = useQuery({
    queryKey: ['analytics', 'latency'],
    queryFn: () => api.getLatencyStats(),
    enabled: status === 'enabled',
    retry: 1,
  });

  const featureQuery = useQuery({
    queryKey: ['analytics', 'features'],
    queryFn: () => api.getFeatureUsage(),
    enabled: status === 'enabled',
    retry: 1,
  });

  const providerQuery = useQuery({
    queryKey: ['analytics', 'providers'],
    queryFn: () => api.getProviderComparison(),
    enabled: status === 'enabled',
    retry: 1,
  });

  const trendQuery = useQuery({
    queryKey: ['analytics', 'trend'],
    queryFn: () => api.getUsageTrend(days),
    enabled: status === 'enabled',
    retry: 1,
  });

  if (status !== 'enabled') {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable status={status} message={message} title="Analytics is unavailable" variant="page" />
      </div>
    );
  }

  const requests = requestsQuery.data ?? [];
  const errors = errorsQuery.data;
  const latency = latencyQuery.data;
  const featureUsage = featureQuery.data ?? [];
  const providerUsage = providerQuery.data ?? [];
  const trend = trendQuery.data ?? [];

  const totalRequests = featureUsage.reduce((sum, f) => sum + f.request_count, 0) || requests.length;
  const totalErrors = errors?.total_errors ?? 0;
  const errorRate = errors?.error_rate ?? 0;

  const featureItems = featureUsage.map((f) => ({
    key: f.feature,
    label: f.feature,
    value: f.request_count,
    tone: 'brand' as const,
  }));

  const providerItems = providerUsage.map((p) => ({
    key: p.provider,
    label: p.provider,
    value: p.request_count,
    tone: 'info' as const,
  }));

  const errorTypeItems = Object.entries(errors?.by_type ?? {}).map(([key, value]) => ({
    key,
    label: key,
    value,
    tone: 'error' as const,
  }));

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Request, error, latency and feature adoption analytics from recorded usage (last {requests.length} requests shown).
        </p>
      </div>

      {requestsQuery.isError && <QueryError message="Could not load analytics." onRetry={() => requestsQuery.refetch()} />}

      {(requestsQuery.isPending || featureQuery.isPending) && <AdminLoading label="Loading analytics…" />}

      {analyticsStatus && !analyticsStatus.enabled && (
        <div className="rounded-lg border border-border bg-surface-1 p-4 text-sm text-muted-foreground">
          Optional analytics collection is currently disabled by an administrator. Historical analytics data remains available.
        </div>
      )}

      <StatGroup label="Overview" columns={4}>
        <KpiTile label="Total requests" value={totalRequests.toLocaleString()} icon={<Hash size={16} />} />
        <KpiTile label="Errors" value={totalErrors.toLocaleString()} icon={<AlertTriangle size={16} />} tone="error" />
        <KpiTile label="Error rate" value={`${(errorRate * 100).toFixed(1)}%`} />
        <KpiTile label="p50 latency" value={latency ? `${Math.round(latency.p50)} ms` : '—'} icon={<Clock size={16} />} />
        <KpiTile label="p90 latency" value={latency ? `${Math.round(latency.p90)} ms` : '—'} />
        <KpiTile label="p99 latency" value={latency ? `${Math.round(latency.p99)} ms` : '—'} />
        <KpiTile label="Features used" value={featureUsage.length.toLocaleString()} icon={<Layers size={16} />} />
        <KpiTile label="Providers used" value={providerUsage.length.toLocaleString()} icon={<Activity size={16} />} />
      </StatGroup>

      <UsageChart data={trend} isLoading={trendQuery.isPending} />

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-3">Feature usage (requests)</h2>
          {featureItems.length ? <RankedList items={featureItems} /> : <p className="text-sm text-muted-foreground">No data.</p>}
        </section>
        <section className="rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-3">Provider usage (requests)</h2>
          {providerItems.length ? <RankedList items={providerItems} /> : <p className="text-sm text-muted-foreground">No data.</p>}
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-3">Errors by type</h2>
          {errorTypeItems.length ? <RankedList items={errorTypeItems} tone="error" /> : <p className="text-sm text-muted-foreground">No errors recorded.</p>}
        </section>
        <section className="rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-3">Errors by provider</h2>
          {Object.keys(errors?.by_provider ?? {}).length ? (
            <RankedList
              items={Object.entries(errors?.by_provider ?? {}).map(([key, value]) => ({
                key,
                label: key,
                value,
                tone: 'error' as const,
              }))}
              tone="error"
            />
          ) : (
            <p className="text-sm text-muted-foreground">No errors recorded.</p>
          )}
        </section>
      </div>

      {featureUsage.length > 0 && (
        <section className="rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-3">Feature adoption details</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="text-left py-2">Feature</th>
                  <th className="text-right py-2">Requests</th>
                  <th className="text-right py-2">Tokens</th>
                  <th className="text-right py-2">Cost</th>
                  <th className="text-right py-2">Avg latency</th>
                </tr>
              </thead>
              <tbody>
                {featureUsage.map((f) => (
                  <tr key={f.feature} className="border-t border-border">
                    <td className="py-2">{f.feature}</td>
                    <td className="py-2 text-right">{f.request_count.toLocaleString()}</td>
                    <td className="py-2 text-right">{f.total_tokens.toLocaleString()}</td>
                    <td className="py-2 text-right">${f.total_cost_usd.toFixed(4)}</td>
                    <td className="py-2 text-right">{f.avg_latency_ms.toFixed(1)} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
