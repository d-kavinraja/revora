'use client';

import { useEffect, useState } from 'react';
import { api, UsageSummary, CostBudget, UsageFilters, Provider, ApiKey, Repository } from '@/lib/api';
import { ChartBarIcon, WalletIcon, TrashIcon, ListFilterIcon, CalendarIcon } from 'lucide-react';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { DateRangeFilter } from '@/components/shared/date-range-filter';
import { useToast } from '@/components/ui/toaster';

export default function UsagePage() {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [budgets, setBudgets] = useState<CostBudget[]>([]);
  
  // Filter options
  const [providers, setProviders] = useState<Provider[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [models, setModels] = useState<string[]>([]);
  
  // Active filters
  const [period, setPeriod] = useState('month');
  const [filters, setFilters] = useState<UsageFilters>({});
  
  // Date range state
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [fromTime, setFromTime] = useState('00:00');
  const [toTime, setToTime] = useState('23:59');
  const [useTime, setUseTime] = useState(false);
  const [showDateFilter, setShowDateFilter] = useState(false);
  
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

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
        
        const activePeriod = (fromDate || toDate) ? 'custom' : period;

        const [sumData, budData] = await Promise.all([
          api.getUsageSummary(activePeriod, queryFilters),
          api.getBudgets(),
        ]);
        if (!controller.signal.aborted) {
          setSummary(sumData);
          setBudgets(budData);
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          console.error('Failed to load usage data', err);
          toast({ title: 'Failed to load usage data', type: 'error' });
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
  }, [period, filters, fromDate, toDate, fromTime, toTime, useTime]);

  const handleDeleteBudget = async (id: string) => {
    try {
      await api.deleteBudget(id);
      setBudgets((prev) => prev.filter((b) => b.id !== id));
      toast({ title: 'Budget deleted', type: 'success' });
    } catch (err) {
      toast({ title: 'Failed to delete budget', type: 'error' });
    }
  };

  const handleFilterChange = (key: keyof UsageFilters, value: string) => {
    setFilters(prev => ({
      ...prev,
      [key]: value === '' ? undefined : value
    }));
  };

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <ChartBarIcon size={28} className="text-brand" />
            Usage & Costs
          </h1>
          <p className="mt-1 text-muted-foreground text-sm">
            Track token usage, costs, and manage budgets across all providers.
          </p>
        </div>
        <div className="flex gap-2 items-center">
          {['today', 'week', 'month'].map((p) => (
            <button
              key={p}
              disabled={!!(fromDate || toDate)}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                period === p && !(fromDate || toDate)
                  ? 'bg-brand text-brand-foreground'
                  : 'bg-surface-2 text-muted-foreground hover:text-foreground border border-border'
              }`}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
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
          className="bg-surface-2 border border-border rounded-md px-3 py-1.5 text-sm outline-none focus:border-brand text-foreground"
          value={filters.provider || ''}
          onChange={(e) => handleFilterChange('provider', e.target.value)}
        >
          <option value="">All Providers</option>
          {providers.map(p => (
            <option key={p.id} value={p.slug}>{p.display_name}</option>
          ))}
        </select>
        
        <select 
          className="bg-surface-2 border border-border rounded-md px-3 py-1.5 text-sm outline-none focus:border-brand text-foreground"
          value={filters.api_key_id || ''}
          onChange={(e) => handleFilterChange('api_key_id', e.target.value)}
        >
          <option value="">All API Keys</option>
          {apiKeys.map(k => (
            <option key={k.id} value={k.id}>{k.label} ({k.provider})</option>
          ))}
        </select>
        
        <select 
          className="bg-surface-2 border border-border rounded-md px-3 py-1.5 text-sm outline-none focus:border-brand text-foreground"
          value={filters.model || ''}
          onChange={(e) => handleFilterChange('model', e.target.value)}
        >
          <option value="">All Models</option>
          {models.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        
        <select 
          className="bg-surface-2 border border-border rounded-md px-3 py-1.5 text-sm outline-none focus:border-brand text-foreground"
          value={filters.repo_id || ''}
          onChange={(e) => handleFilterChange('repo_id', e.target.value)}
        >
          <option value="">All Repositories</option>
          {repos.map(r => (
            <option key={r.id} value={r.id}>{r.full_name}</option>
          ))}
        </select>
        
        {Object.keys(filters).some(k => filters[k as keyof UsageFilters] !== undefined) && (
          <button 
            onClick={() => setFilters({})}
            className="text-xs font-medium text-muted-foreground hover:text-foreground transition-colors ml-auto"
          >
            Clear Filters
          </button>
        )}
      </div>

      {loading && !summary ? (
        <div className="flex flex-col items-center justify-center min-h-[30vh]">
          <LoaderIcon size={24} className="text-brand mb-2 animate-spin" />
          <span className="text-sm text-muted-foreground">Loading usage data...</span>
        </div>
      ) : summary ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div className="rounded-xl border border-border bg-surface-1 p-4">
              <div className="text-xs text-muted-foreground font-semibold uppercase tracking-wide">Total Cost</div>
              <div className="text-2xl font-bold text-foreground mt-1">${summary.total_cost_usd.toFixed(4)}</div>
            </div>
            <div className="rounded-xl border border-border bg-surface-1 p-4">
              <div className="text-xs text-muted-foreground font-semibold uppercase tracking-wide">Total Tokens</div>
              <div className="text-2xl font-bold text-foreground mt-1">{summary.total_tokens.toLocaleString()}</div>
            </div>
            <div className="rounded-xl border border-border bg-surface-1 p-4">
              <div className="text-xs text-muted-foreground font-semibold uppercase tracking-wide">Requests</div>
              <div className="text-2xl font-bold text-foreground mt-1">{summary.request_count}</div>
            </div>
            <div className="rounded-xl border border-border bg-surface-1 p-4">
              <div className="text-xs text-muted-foreground font-semibold uppercase tracking-wide">Input / Output</div>
              <div className="text-lg font-bold text-foreground mt-1">
                {summary.input_tokens.toLocaleString()} / {summary.output_tokens.toLocaleString()}
              </div>
            </div>
          </div>

          {Object.keys(summary.by_provider).length > 0 && (
            <div className="rounded-xl border border-border bg-surface-1 p-5 mb-8">
              <h2 className="text-lg font-bold text-foreground mb-4">Cost by Provider</h2>
              <div className="space-y-3">
                {Object.entries(summary.by_provider).map(([provider, cost]) => (
                  <div key={provider} className="flex items-center justify-between">
                    <span className="text-sm text-foreground font-medium">{provider}</span>
                    <div className="flex items-center gap-3">
                      <div className="w-32 h-2 bg-surface-3 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-brand rounded-full"
                          style={{ width: `${Math.min(100, (cost / (summary.total_cost_usd || 1)) * 100)}%` }}
                        />
                      </div>
                      <span className="text-sm font-mono text-muted-foreground">${(cost as number).toFixed(4)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="rounded-xl border border-border bg-surface-1 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
                <WalletIcon size={18} className="text-brand" />
                Budgets
              </h2>
            </div>
            {budgets.length === 0 ? (
              <p className="text-sm text-muted-foreground">No budgets configured. Set spending limits to control costs.</p>
            ) : (
              <div className="space-y-3">
                {budgets.map((budget) => (
                  <div key={budget.id} className="flex items-center justify-between p-3 rounded-lg bg-surface-2 border border-border">
                    <div>
                      <span className="text-sm font-medium text-foreground">{budget.budget_type} limit</span>
                      {budget.provider && <span className="ml-2 text-xs text-muted-foreground">for {budget.provider}</span>}
                      <div className="text-xs text-muted-foreground mt-0.5">
                        ${budget.spent_usd.toFixed(4)} / ${budget.limit_usd.toFixed(2)}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-2 bg-surface-3 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${budget.spent_usd / budget.limit_usd > 0.8 ? 'bg-error' : 'bg-brand'}`}
                          style={{ width: `${Math.min(100, (budget.spent_usd / budget.limit_usd) * 100)}%` }}
                        />
                      </div>
                      <button
                        onClick={() => handleDeleteBudget(budget.id)}
                        className="p-1.5 text-muted-foreground hover:text-error rounded-lg transition-colors"
                      >
                        <TrashIcon size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}


