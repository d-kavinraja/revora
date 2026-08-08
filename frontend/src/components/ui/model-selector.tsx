import { useEffect, useState } from 'react';
import { api, DiscoveredModel } from '@/lib/api';
import { RefreshCwIcon, CheckIcon, ChevronDownIcon } from 'lucide-react';
import { useToast } from './toaster';

interface ModelSelectorProps {
  providerSlug: string;
}

export function ModelSelector({ providerSlug }: ModelSelectorProps) {
  const [models, setModels] = useState<DiscoveredModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const { toast } = useToast();

  const loadModels = async () => {
    setLoading(true);
    try {
      const data = await api.getProviderModels(providerSlug);
      setModels(data);
      if (data.length > 0) {
        setLastSynced(new Date(data[0].last_synced_at).toLocaleString());
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadModels();
  }, [providerSlug]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const data = await api.syncProviderModels(providerSlug);
      setModels(data);
      if (data.length > 0) {
        setLastSynced(new Date(data[0].last_synced_at).toLocaleString());
      }
      toast({ title: 'Models refreshed successfully', type: 'success' });
    } catch (err: any) {
      toast({ title: 'Failed to refresh models', description: err.response?.data?.detail || err.message, type: 'error' });
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="mt-4 border-t border-border pt-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h4 className="text-sm font-medium text-foreground">Available Models</h4>
          {lastSynced && <p className="text-xs text-muted-foreground">Last synced: {lastSynced}</p>}
        </div>
        <button
          onClick={handleSync}
          disabled={syncing || loading}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-surface-2 hover:bg-surface-3 transition-colors border border-border text-foreground disabled:opacity-50"
        >
          <RefreshCwIcon size={14} className={syncing ? 'animate-spin' : ''} />
          {syncing ? 'Syncing...' : 'Refresh'}
        </button>
      </div>
      
      {loading ? (
        <div className="text-sm text-muted-foreground animate-pulse">Loading models...</div>
      ) : models.length === 0 ? (
        <div className="text-sm text-muted-foreground bg-surface-2 p-3 rounded-md border border-border/50">
          No models found. Try syncing or check your API key.
        </div>
      ) : (
        <div className="relative">
          <select className="w-full appearance-none bg-surface-2 border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-brand">
            <option value="">Select a model...</option>
            {models.map(m => (
              <option key={m.id} value={m.model_id}>
                {m.display_name} ({m.is_free ? 'FREE' : 'PAID'})
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-muted-foreground">
            <ChevronDownIcon size={16} />
          </div>
        </div>
      )}
    </div>
  );
}
