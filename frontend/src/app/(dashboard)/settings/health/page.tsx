'use client';

import { useEffect, useState, useCallback } from 'react';
import { api, ProviderHealth, FailoverLog } from '@/lib/api';
import { ActivityIcon, CircleCheckIcon, TriangleAlertIcon } from '@animateicons/react/lucide';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { useToast } from '@/components/ui/toaster';
import { ProviderIcon } from '@/components/ui/provider-icon';

export default function HealthPage() {
  const [healthData, setHealthData] = useState<ProviderHealth[]>([]);
  const [failovers, setFailovers] = useState<FailoverLog[]>([]);
  const [circuitBreakers, setCircuitBreakers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

  const loadData = useCallback(async () => {
    try {
      const [hData, fData, cbData] = await Promise.all([
        api.getProviderHealth(),
        api.getFailovers(),
        api.getCircuitBreakers(),
      ]);
      setHealthData(hData);
      setFailovers(fData);
      setCircuitBreakers(cbData);
    } catch (err) {
      console.error('Failed to load health data', err);
      toast({ title: 'Failed to load health data', type: 'error' });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCheckHealth = async (slug: string) => {
    try {
      await api.checkProviderHealth(slug);
      toast({ title: `Health check initiated for ${slug}`, type: 'info' });
      // Refresh data after health check
      await loadData();
    } catch (err) {
      toast({ title: 'Health check failed', type: 'error' });
    }
  };

  const getStatusIcon = (status: string) => {
    if (status === 'healthy') return <CircleCheckIcon size={14} className="text-success" />;
    if (status === 'degraded') return <TriangleAlertIcon size={14} className="text-warning" />;
    return <TriangleAlertIcon size={14} className="text-error" />;
  };

  const getStatusColor = (status: string) => {
    if (status === 'healthy') return 'bg-success/5 border-success/20 text-success';
    if (status === 'degraded') return 'bg-warning/5 border-warning/20 text-warning';
    return 'bg-error/5 border-error/20 text-error';
  };

  const getCircuitColor = (state: string) => {
    if (state === 'closed') return 'text-success';
    if (state === 'half_open') return 'text-warning';
    return 'text-error';
  };

  if (loading) {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 flex flex-col items-center justify-center min-h-[50vh]">
        <LoaderIcon size={24} className="text-brand mb-2 animate-spin" />
        <span className="text-sm text-muted-foreground">Loading health data...</span>
      </div>
    );
  }

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="mb-8">
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <ActivityIcon size={28} className="text-brand" />
          Health Monitor
        </h1>
        <p className="mt-1 text-muted-foreground text-sm">
          Provider health status, circuit breaker states, and failover events.
        </p>
      </div>

      {healthData.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface-1 p-8 text-center mb-8">
          <ActivityIcon size={32} className="mx-auto text-muted-foreground mb-3 opacity-50" />
          <h3 className="font-semibold text-foreground text-base mb-1">No Configured Providers</h3>
          <p className="text-sm text-muted-foreground max-w-md mx-auto mb-4">
            You don't have any active API credentials registered for your account. Add an API key in Settings &rarr; API Keys to monitor provider health.
          </p>
          <a href="/settings/api-keys" className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-lg bg-brand text-white hover:bg-brand-hover transition-colors">
            + Add API Key
          </a>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
          {healthData.map((h) => (
            <div key={h.provider} className="cursor-target rounded-xl border border-border bg-surface-1 p-5 backdrop-blur-md">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="shrink-0 flex items-center justify-center w-6 h-6 rounded bg-surface-2 border border-border">
                    <ProviderIcon slug={h.provider} size={14} />
                  </span>
                  <span className="font-bold text-foreground">{h.provider}</span>
                  <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border ${getStatusColor(h.status)}`}>
                    {getStatusIcon(h.status)}
                    {h.status}
                  </span>
                </div>
                <button
                  onClick={() => handleCheckHealth(h.provider)}
                  className="text-xs font-semibold px-2 py-1 rounded-lg bg-surface-2 text-muted-foreground hover:text-foreground border border-border transition-colors"
                >
                  Check
                </button>
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-muted-foreground">Avg Latency</span>
                  <div className="font-mono text-foreground">{h.avg_latency_ms.toFixed(0)}ms</div>
                </div>
                <div>
                  <span className="text-muted-foreground">Success Rate</span>
                  <div className="font-mono text-foreground">{(h.success_rate * 100).toFixed(1)}%</div>
                </div>
                <div>
                  <span className="text-muted-foreground">Requests</span>
                  <div className="font-mono text-foreground">{h.total_requests}</div>
                </div>
                <div>
                  <span className="text-muted-foreground">Circuit</span>
                  <div className={`font-mono font-bold ${getCircuitColor(h.circuit_state)}`}>{h.circuit_state}</div>
                </div>
              </div>
              {h.last_error && (
                <div className="mt-3 p-2 rounded-lg bg-error/5 border border-error/20 text-xs text-error">
                  {h.last_error}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {failovers.length > 0 && (
        <div className="rounded-xl border border-border bg-surface-1 p-5">
          <h2 className="text-lg font-bold text-foreground mb-4">Recent Failovers</h2>
          <div className="space-y-2">
            {failovers.slice(0, 10).map((f) => (
              <div key={f.id} className="flex items-center justify-between p-3 rounded-lg bg-surface-2 border border-border text-xs">
                <div className="flex items-center">
                  <span className="flex items-center gap-1.5 text-error font-medium">
                    <ProviderIcon slug={f.failed_provider} size={12} />
                    {f.failed_provider}/{f.failed_model}
                  </span>
                  <span className="mx-2 text-muted-foreground">&rarr;</span>
                  <span className="flex items-center gap-1.5 text-success font-medium">
                    <ProviderIcon slug={f.fallback_provider} size={12} />
                    {f.fallback_provider}/{f.fallback_model}
                  </span>
                </div>
                <div className="text-muted-foreground">{new Date(f.created_at).toLocaleString()}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


