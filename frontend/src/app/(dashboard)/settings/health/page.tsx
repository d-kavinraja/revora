'use client';

import { useEffect, useState, useCallback } from 'react';
import { api, ProviderHealth, FailoverLog, OperationJob } from '@/lib/api';
import { pollOperation } from '@/lib/use-operation-job';
import { ActivityIcon, CircleCheckIcon, TriangleAlertIcon } from '@animateicons/react/lucide';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { useToast } from '@/components/ui/toaster';
import { ProviderIcon } from '@/components/ui/provider-icon';

export default function HealthPage() {
  const [healthData, setHealthData] = useState<ProviderHealth[]>([]);
  const [failovers, setFailovers] = useState<FailoverLog[]>([]);
  const [circuitBreakers, setCircuitBreakers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [checkingProvider, setCheckingProvider] = useState<string | null>(null);
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

  const resumeProviderCheck = useCallback(
    async (job: OperationJob) => {
      const provider = String(job.payload?.provider ?? '');
      if (!provider) return;
      setCheckingProvider(provider);
      try {
        await pollOperation(job.id, (updated) => {
          if (updated.status === 'completed' || updated.status === 'failed') {
            void loadData();
          }
        });
        toast({
          title: `Health check finished for ${provider}`,
          type: 'success',
        });
        await loadData();
      } catch (err) {
        toast({ title: `Health check failed for ${provider}`, type: 'error' });
      } finally {
        setCheckingProvider(null);
      }
    },
    [loadData, toast],
  );

  useEffect(() => {
    loadData();
    void api
      .listOperations({ active_only: true, operation_type: 'provider_health_check' })
      .then((jobs) => {
        for (const job of jobs) {
          void resumeProviderCheck(job);
        }
      })
      .catch(() => undefined);
  }, [loadData, resumeProviderCheck]);

  const handleCheckHealth = async (slug: string) => {
    if (checkingProvider) return;
    setCheckingProvider(slug);
    try {
      const job = await api.checkProviderHealth(slug);
      toast({ title: `Health check started for ${slug}`, type: 'info' });
      const final = await pollOperation(job.id, (updated) => {
        if (updated.status === 'completed' || updated.status === 'failed') {
          void loadData();
        }
      });
      const result = final.result;
      toast({
        title: `Health check ${final.status} for ${slug}`,
        description:
          result?.message ??
          (result?.model ? `Tested ${result.model}` : final.error_text ?? undefined),
        type: final.status === 'completed' ? 'success' : 'error',
      });
      await loadData();
    } catch (err) {
      toast({ title: 'Health check failed', type: 'error' });
    } finally {
      setCheckingProvider(null);
    }
  };

  const getStatusIcon = (status: string) => {
    if (status === 'healthy') return <CircleCheckIcon size={14} className="text-success" />;
    if (status === 'degraded') return <TriangleAlertIcon size={14} className="text-warning" />;
    return <TriangleAlertIcon size={14} className="text-error" />;
  };

  const getStatusColor = (status: string) => {
    if (status === 'healthy') return 'bg-success/10 border-success/30 text-success';
    if (status === 'degraded') return 'bg-warning/10 border-warning/30 text-warning';
    return 'bg-error/10 border-error/30 text-error';
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
            <div key={h.provider} className="cursor-target rounded-xl border border-border bg-surface-1 p-5">
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
                  disabled={checkingProvider !== null}
                  className="text-xs font-semibold px-2 py-1 rounded-lg bg-background text-foreground hover:bg-surface-2 border border-border transition-colors disabled:opacity-50"
                >
                  {checkingProvider === h.provider ? 'Checking...' : 'Check'}
                </button>
              </div>
               <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-muted-foreground">Avg Latency</span>
                  <div className="font-mono text-foreground">
                    {h.total_requests > 0 ? `${h.avg_latency_ms.toFixed(0)}ms` : '—'}
                  </div>
                </div>
                <div>
                  <span className="text-muted-foreground">Success Rate</span>
                  <div className="font-mono text-foreground">
                    {h.total_requests > 0 ? `${(h.success_rate * 100).toFixed(1)}%` : '—'}
                  </div>
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
              {h.last_checked_at && (
                <div className="mt-3 text-xs text-muted-foreground">
                  Last checked {new Date(h.last_checked_at).toLocaleString()}
                  {h.last_model ? ` · ${h.last_model}` : ''}
                  {h.last_latency_ms != null ? ` · ${h.last_latency_ms.toFixed(0)}ms` : ''}
                </div>
              )}
              {h.last_error && (
                <div className="mt-3 p-2 rounded-lg bg-error/10 border border-error/30 text-xs text-error">
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


