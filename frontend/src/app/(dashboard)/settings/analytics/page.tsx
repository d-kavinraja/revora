'use client';

import { useEffect, useState } from 'react';
import { api, LLMRequestLog, Provider, ApiKey, Repository, UsageFilters } from '@/lib/api';
import { ActivityIcon } from '@animateicons/react/lucide';
import { ListFilterIcon, CalendarIcon } from 'lucide-react';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { DateRangeFilter } from '@/components/shared/date-range-filter';
import { useToast } from '@/components/ui/toaster';

export default function AnalyticsPage() {
  const [requests, setRequests] = useState<LLMRequestLog[]>([]);
  const [errors, setErrors] = useState<{ total_errors: number; by_type: Record<string, number>; by_provider: Record<string, number>; error_rate: number } | null>(null);
  const [latency, setLatency] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

  // Filter options
  const [providers, setProviders] = useState<Provider[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [models, setModels] = useState<string[]>([]);
  
  // Active filters
  const [filters, setFilters] = useState<UsageFilters>({});
  
  // Date range state
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [fromTime, setFromTime] = useState('00:00');
  const [toTime, setToTime] = useState('23:59');
  const [useTime, setUseTime] = useState(false);
  const [showDateFilter, setShowDateFilter] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    async function loadOptions() {
      try {
        const [provData, keyData, repoData, modelData] = await Promise.all([
          api.getProviders(),
          api.getApiKeys(),
          api.getRepositories(),
          api.getAvailableModels()
        ]);
        if (!controller.signal.aborted) {
          setProviders(provData);
          setApiKeys(keyData);
          setRepos(repoData);
          
          // Extract unique model names
          const allModels = new Set<string>();
          Object.values(modelData).forEach(models => {
            models.forEach(m => allModels.add(m.model_name));
          });
          setModels(Array.from(allModels).sort());
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          console.error('Failed to load filter options', err);
        }
      }
    }
    loadOptions();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    async function loadData() {
      setLoading(true);
      try {
        const queryFilters = { ...filters };
        if (fromDate) {
          queryFilters.start_date = useTime && fromTime ? `${fromDate}T${fromTime}:00` : `${fromDate}T00:00:00`;
        }
        if (toDate) {
          queryFilters.end_date = useTime && toTime ? `${toDate}T${toTime}:59` : `${toDate}T23:59:59`;
        }

        const [reqData, errData, latData] = await Promise.all([
          api.getRequestLogs(50, 0, queryFilters),
          api.getErrorSummary(queryFilters),
          api.getLatencyStats(queryFilters),
        ]);
        if (!controller.signal.aborted) {
          setRequests(reqData);
          setErrors(errData);
          setLatency(latData);
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          console.error('Failed to load analytics', err);
          toast({ title: 'Failed to load analytics', type: 'error' });
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }
    loadData();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, fromDate, toDate, fromTime, toTime, useTime]);

  const handleFilterChange = (key: keyof UsageFilters, value: string) => {
    setFilters(prev => ({
      ...prev,
      [key]: value === '' ? undefined : value
    }));
  };

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <ActivityIcon size={28} className="text-brand" />
            Analytics
          </h1>
          <p className="mt-1 text-muted-foreground text-sm">
            Request logs, latency statistics, and error analysis.
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <button
            onClick={() => setShowDateFilter(o => !o)}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
              showDateFilter || (fromDate || toDate)
                ? 'bg-brand/10 border-brand/30 text-brand'
                : 'bg-surface-2 border-border text-muted-foreground hover:text-foreground hover:bg-white/[0.04]'
            }`}
          >
            <CalendarIcon size={13} />
            Date Filter
            {(fromDate || toDate) && (
              <span className="ml-1 w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
            )}
          </button>
        </div>
      </div>

      {/* Date Range Filter Panel */}
      {showDateFilter && (
        <DateRangeFilter
          fromDate={fromDate}
          toDate={toDate}
          fromTime={fromTime}
          toTime={toTime}
          useTime={useTime}
          onFromDate={setFromDate}
          onToDate={setToDate}
          onFromTime={setFromTime}
          onToTime={setToTime}
          onToggleTime={() => setUseTime(u => !u)}
          onClear={() => {
            setFromDate('');
            setToDate('');
            setFromTime('00:00');
            setToTime('23:59');
            setUseTime(false);
          }}
          className="mb-6 w-full"
        />
      )}

      {/* Filters Bar */}
      <div className="bg-surface-1 border border-border rounded-xl p-4 mb-8 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground mr-2">
          <ListFilterIcon size={16} className="text-muted-foreground" />
          Filters:
        </div>
        
        <select 
          className="cursor-target bg-surface-2 border border-border rounded-md px-3 py-1.5 text-sm outline-none focus:border-brand text-foreground"
          value={filters.provider || ''}
          onChange={(e) => handleFilterChange('provider', e.target.value)}
        >
          <option value="">All Providers</option>
          {providers.map(p => (
            <option key={p.id} value={p.slug}>{p.display_name}</option>
          ))}
        </select>
        
        <select 
          className="cursor-target bg-surface-2 border border-border rounded-md px-3 py-1.5 text-sm outline-none focus:border-brand text-foreground"
          value={filters.api_key_id || ''}
          onChange={(e) => handleFilterChange('api_key_id', e.target.value)}
        >
          <option value="">All API Keys</option>
          {apiKeys.map(k => (
            <option key={k.id} value={k.id}>{k.label} ({k.provider})</option>
          ))}
        </select>
        
        <select 
          className="cursor-target bg-surface-2 border border-border rounded-md px-3 py-1.5 text-sm outline-none focus:border-brand text-foreground"
          value={filters.model || ''}
          onChange={(e) => handleFilterChange('model', e.target.value)}
        >
          <option value="">All Models</option>
          {models.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        
        <select 
          className="cursor-target bg-surface-2 border border-border rounded-md px-3 py-1.5 text-sm outline-none focus:border-brand text-foreground"
          value={filters.repo_id || ''}
          onChange={(e) => handleFilterChange('repo_id', e.target.value)}
        >
          <option value="">All Repositories</option>
          {repos.map(r => (
            <option key={r.id} value={r.id}>{r.full_name}</option>
          ))}
        </select>
        
        {(Object.keys(filters).some(k => filters[k as keyof UsageFilters] !== undefined) || fromDate || toDate) && (
          <button 
            onClick={() => {
                setFilters({});
                setFromDate('');
                setToDate('');
                setFromTime('00:00');
                setToTime('23:59');
                setUseTime(false);
            }}
            className="cursor-target text-xs font-medium text-muted-foreground hover:text-foreground transition-colors ml-auto"
          >
            Clear Filters
          </button>
        )}
      </div>

      {loading && !latency ? (
        <div className="flex flex-col items-center justify-center min-h-[30vh]">
          <LoaderIcon size={24} className="text-brand mb-2 animate-spin" />
          <span className="text-sm text-muted-foreground">Loading analytics...</span>
        </div>
      ) : (
        <>
          {latency && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
              <div className="cursor-target rounded-xl border border-border bg-surface-1 p-4">
                <div className="text-xs text-muted-foreground font-semibold uppercase tracking-wide">P50 Latency</div>
                <div className="text-2xl font-bold text-foreground mt-1">{latency.p50?.toFixed(0) || 0}ms</div>
              </div>
              <div className="cursor-target rounded-xl border border-border bg-surface-1 p-4">
                <div className="text-xs text-muted-foreground font-semibold uppercase tracking-wide">P90 Latency</div>
                <div className="text-2xl font-bold text-foreground mt-1">{latency.p90?.toFixed(0) || 0}ms</div>
              </div>
              <div className="rounded-xl border border-border bg-surface-1 p-4">
                <div className="text-xs text-muted-foreground font-semibold uppercase tracking-wide">P99 Latency</div>
                <div className="text-2xl font-bold text-foreground mt-1">{latency.p99?.toFixed(0) || 0}ms</div>
              </div>
              <div className="rounded-xl border border-border bg-surface-1 p-4">
                <div className="text-xs text-muted-foreground font-semibold uppercase tracking-wide">Avg Latency</div>
                <div className="text-2xl font-bold text-foreground mt-1">{latency.avg?.toFixed(0) || 0}ms</div>
              </div>
            </div>
          )}

          {errors && (
            <div className="rounded-xl border border-border bg-surface-1 p-5 mb-8">
              <h2 className="text-lg font-bold text-foreground mb-3">Error Summary</h2>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Total Errors:</span>
                  <span className="ml-2 font-bold text-foreground">{errors.total_errors}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Error Rate:</span>
                  <span className="ml-2 font-bold text-foreground">{(errors.error_rate * 100).toFixed(1)}%</span>
                </div>
              </div>
              {Object.keys(errors.by_type).length > 0 && (
                <div className="mt-3">
                  <span className="text-xs text-muted-foreground font-semibold">By Type:</span>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {Object.entries(errors.by_type).map(([type, count]) => (
                      <span key={type} className="text-xs px-2 py-0.5 rounded-full bg-error/10 text-error border border-error/20">
                        {type}: {count}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="rounded-xl border border-border bg-surface-1 p-5">
            <h2 className="text-lg font-bold text-foreground mb-4">Recent Requests</h2>
            {requests.length === 0 ? (
              <p className="text-sm text-muted-foreground">No requests logged yet.</p>
            ) : (
              <div className="space-y-2">
                {requests.slice(0, 20).map((req) => (
                  <div key={req.id} className="flex items-center justify-between p-3 rounded-lg bg-surface-2 border border-border text-xs">
                    <div className="flex items-center gap-3">
                      <span className={`w-2 h-2 rounded-full ${req.status === 'success' ? 'bg-success' : req.status === 'error' ? 'bg-error' : 'bg-warning'}`} />
                      <span className="font-medium text-foreground">{req.provider}/{req.model}</span>
                      <span className="text-muted-foreground">{req.feature}</span>
                    </div>
                    <div className="flex items-center gap-4 text-muted-foreground">
                      <span>{req.latency_ms.toFixed(0)}ms</span>
                      <span>${req.cost_usd.toFixed(4)}</span>
                      <span>{new Date(req.started_at).toLocaleString()}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

