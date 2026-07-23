'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { api, Repository, ApiKey, ModelMetadata } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { FolderIcon, ClipboardIcon, SettingsIcon, XIcon, TriangleAlertIcon } from '@animateicons/react/lucide';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonList } from '@/components/shared/skeleton';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/components/ui/toaster';
import { ProviderIcon } from '@/components/ui/provider-icon';

function LangBadge({ lang }: { lang: string | null }) {
  if (!lang) return null;
  const colors: Record<string, string> = {
    Python: 'bg-blue-500/15 text-blue-300',
    TypeScript: 'bg-sky-500/15 text-sky-300',
    JavaScript: 'bg-yellow-500/15 text-yellow-300',
    Go: 'bg-cyan-500/15 text-cyan-300',
    Rust: 'bg-orange-500/15 text-orange-300',
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[lang] ?? 'bg-muted text-muted-foreground'}`}>
      {lang}
    </span>
  );
}

function ConfigModal({
  repo,
  availableModels,
  apiKeys,
  onClose,
  onSave,
}: {
  repo: Repository;
  availableModels: Record<string, ModelMetadata[]>;
  apiKeys: ApiKey[];
  onClose: () => void;
  onSave: (config: { assigned_provider?: string; assigned_model?: string; assigned_key_id?: string; reviews_enabled?: boolean }) => Promise<void>;
}) {
  const providers = Object.keys(availableModels);
  const dialogRef = useRef<HTMLDivElement>(null);
  
  const [selectedProvider, setSelectedProvider] = useState(() => {
    const saved = repo.settings?.assigned_provider;
    return (saved && providers.includes(saved)) ? saved : (providers[0] ?? '');
  });
  
  const providerKeys = apiKeys.filter(k => k.provider.toLowerCase() === selectedProvider.toLowerCase() && k.is_valid);
  
  const [selectedKeyId, setSelectedKeyId] = useState(() => {
    const saved = repo.settings?.assigned_key_id;
    return (saved && providerKeys.some(k => k.id === saved)) ? saved : (providerKeys[0]?.id ?? '');
  });

  const allModels = availableModels[selectedProvider] || [];

  const [showDeprecated, setShowDeprecated] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [showUnavailable, setShowUnavailable] = useState(false);

  const models = allModels.filter((m) => {
    if (!showUnavailable && !m.accessible) return false;
    if (!showDeprecated && m.deprecated) return false;
    if (!showPreview && (m.preview || m.experimental)) return false;
    return true;
  });

  const [selectedModel, setSelectedModel] = useState(() => {
    const saved = repo.settings?.assigned_model;
    if (saved && models.some(m => m.model_name === saved)) return saved;
    return models.find(m => m.accessible)?.model_name || '';
  });

  const [reviewsEnabled, setReviewsEnabled] = useState(repo.reviews_enabled);
  const [saving, setSaving] = useState(false);
  const settingsRef = useRef<any>(null);
  const { toast } = useToast();

  useEffect(() => {
    const keys = apiKeys.filter(k => k.provider.toLowerCase() === selectedProvider.toLowerCase() && k.is_valid);
    if (keys.length > 0 && !keys.some(k => k.id === selectedKeyId)) {
      setSelectedKeyId(keys[0].id);
    } else if (keys.length === 0) {
      setSelectedKeyId('');
    }
  }, [selectedProvider, apiKeys, selectedKeyId]);

  useEffect(() => {
    if (selectedProvider && models.length > 0 && !models.some(m => m.model_name === selectedModel)) {
      const firstAccessible = models.find(m => m.accessible);
      if (firstAccessible) {
        setSelectedModel(firstAccessible.model_name);
      }
    }
  }, [selectedProvider, models, selectedModel]);

  useEffect(() => {
    settingsRef.current?.startAnimation?.();
  }, []);

  // Trap focus & handle escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    dialogRef.current?.focus();
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({
        assigned_provider: selectedProvider || undefined,
        assigned_model: selectedModel || undefined,
        assigned_key_id: selectedKeyId || undefined,
        reviews_enabled: reviewsEnabled,
      });
      onClose(); // Only close on success
    } catch (err: any) {
      toast({
        title: 'Failed to save configuration',
        description: err.response?.data?.detail || err.message,
        type: 'error',
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        tabIndex={-1}
        className="w-full max-w-md bg-surface-1 border border-border rounded-xl shadow-2xl p-6 outline-none max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 id="modal-title" className="text-lg font-semibold text-foreground">Configure Model</h3>
            <p className="text-xs text-muted-foreground mt-0.5">{repo.full_name}</p>
          </div>
          <button onClick={onClose} className="p-1 rounded text-muted-foreground hover:text-foreground transition-colors cursor-pointer" aria-label="Close dialog">
            <XIcon size={18} />
          </button>
        </div>

        {providers.length === 0 ? (
          <div className="text-center py-6">
            <p className="text-sm text-muted-foreground">No API keys configured.</p>
            <p className="text-xs text-muted-foreground mt-1">Add an API key in Settings to enable model selection.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Provider Selector */}
            <div>
              <label htmlFor="provider-select" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Provider</label>
              <select
                id="provider-select"
                value={selectedProvider}
                onChange={(e) => setSelectedProvider(e.target.value)}
                className="w-full mt-1.5 px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 cursor-pointer"
              >
                {providers.map((p) => (
                  <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
                ))}
              </select>
            </div>

            {/* API Key Selector */}
            {providerKeys.length > 0 && (
              <div>
                <label htmlFor="key-select" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">API Key</label>
                <select
                  id="key-select"
                  value={selectedKeyId}
                  onChange={(e) => setSelectedKeyId(e.target.value)}
                  className="w-full mt-1.5 px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 cursor-pointer"
                >
                  {providerKeys.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.label} ({k.masked_key})
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Model Selector */}
            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="model-select" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Model</label>
                <div className="flex gap-2">
                  <label className="flex items-center gap-1 cursor-pointer text-[10px] text-muted-foreground">
                    <input type="checkbox" checked={showPreview} onChange={(e) => setShowPreview(e.target.checked)} className="accent-brand rounded-sm" /> Preview
                  </label>
                  <label className="flex items-center gap-1 cursor-pointer text-[10px] text-muted-foreground">
                    <input type="checkbox" checked={showDeprecated} onChange={(e) => setShowDeprecated(e.target.checked)} className="accent-brand rounded-sm" /> Deprecated
                  </label>
                  <label className="flex items-center gap-1 cursor-pointer text-[10px] text-muted-foreground">
                    <input type="checkbox" checked={showUnavailable} onChange={(e) => setShowUnavailable(e.target.checked)} className="accent-brand rounded-sm" /> Unavailable
                  </label>
                </div>
              </div>
              <select
                id="model-select"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full mt-1.5 px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 cursor-pointer"
              >
                {models.map((m) => {
                  let badge = '';
                  if (!m.accessible) badge = ' [Unavailable]';
                  else if (m.deprecated) badge = ' [Deprecated]';
                  else if (m.preview || m.experimental) badge = ' [Preview]';
                  else if (m.enterprise_only) badge = ' [Enterprise]';
                  
                  return (
                    <option key={m.model_name} value={m.model_name} disabled={!m.accessible} title={!m.accessible ? 'This model is inaccessible with your current API key permissions.' : ''}>
                      {m.model_name}{badge}
                    </option>
                  );
                })}
              </select>
            </div>

            {/* Reviews Toggle */}
            <div className="flex items-center justify-between py-2">
              <div>
                <label id="reviews-label" className="text-sm font-medium text-foreground">Reviews Enabled</label>
                <p className="text-xs text-muted-foreground">Automatically review pull requests</p>
              </div>
              <button
                role="switch"
                aria-checked={reviewsEnabled}
                aria-labelledby="reviews-label"
                onClick={() => setReviewsEnabled(!reviewsEnabled)}
                className={`relative w-10 h-5 rounded-full transition-colors cursor-pointer ${reviewsEnabled ? 'bg-brand' : 'bg-muted'}`}
              >
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${reviewsEnabled ? 'left-5.5 translate-x-0' : 'left-0.5'}`} />
              </button>
            </div>

            {/* Save Button */}
            <button
              onClick={handleSave}
              disabled={saving || !selectedModel}
              className="w-full py-2.5 bg-brand hover:bg-brand-hover disabled:opacity-50 text-brand-foreground rounded-lg text-sm font-semibold transition-colors cursor-pointer"
            >
              {saving ? 'Saving...' : 'Save Configuration'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function RepositoryCard({
  repo,
  syncingRepoId,
  configuringRepoId,
  handleSync,
  onConfigure,
  apiKeys,
}: {
  repo: Repository;
  syncingRepoId: string | null;
  configuringRepoId: string | null;
  handleSync: (id: string) => void;
  onConfigure: (repo: Repository) => void;
  apiKeys: ApiKey[];
}) {
  const folderRef = useRef<any>(null);
  const reviewsRef = useRef<any>(null);
  const settingsRef = useRef<any>(null);

  const assignedModel = repo.settings?.assigned_model;
  const assignedProvider = repo.settings?.assigned_provider;
  const assignedKeyId = repo.settings?.assigned_key_id;
  const keyObj = apiKeys.find(k => k.id === assignedKeyId);
  const keyLabel = keyObj ? ` (${keyObj.label})` : '';

  return (
    <div
      onMouseEnter={() => {
        folderRef.current?.startAnimation();
        reviewsRef.current?.startAnimation();
        settingsRef.current?.startAnimation();
      }}
      onMouseLeave={() => {
        folderRef.current?.stopAnimation();
        reviewsRef.current?.stopAnimation();
        settingsRef.current?.stopAnimation();
      }}
      className="cursor-target rounded-xl border border-border bg-surface-1 hover:border-brand/25 transition-all duration-150 p-5 group flex flex-col justify-between"
    >
      <div>
        <div className="flex items-start justify-between mb-2 gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <FolderIcon ref={folderRef} size={18} isAnimated={false} className="text-muted-foreground group-hover:text-brand transition-colors shrink-0" />
            <span className="font-semibold text-foreground text-sm truncate">{repo.full_name}</span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <LangBadge lang={repo.language} />
            {repo.is_private && (
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-muted text-muted-foreground">
                Private
              </span>
            )}
          </div>
        </div>

        {repo.description && (
          <p className="text-muted-foreground text-xs mb-3 line-clamp-2">{repo.description}</p>
        )}

        {assignedModel && (
          <div className="mb-3">
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-brand/10 text-brand border border-brand/20">
              {assignedProvider && <ProviderIcon slug={assignedProvider} size={10} />}
              {assignedProvider}: {assignedModel}{keyLabel}
            </span>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <ClipboardIcon ref={reviewsRef} size={14} isAnimated={false} />
            {repo.total_reviews} reviews
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            disabled={configuringRepoId === repo.id || syncingRepoId === repo.id}
            onClick={() => onConfigure(repo)}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors cursor-pointer disabled:opacity-50"
            title="Configure model"
          >
            {configuringRepoId === repo.id ? (
              <LoaderIcon size={14} className="text-muted-foreground" animate />
            ) : (
              <SettingsIcon ref={settingsRef} size={14} isAnimated={false} />
            )}
          </button>

          <button
            disabled={syncingRepoId !== null}
            onClick={() => handleSync(repo.id)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-white/[0.04] hover:bg-white/[0.08] text-muted-foreground hover:text-foreground rounded-lg text-xs font-medium transition-colors cursor-pointer border border-border disabled:opacity-50"
          >
            {syncingRepoId === repo.id ? (
              <>
                <LoaderIcon size={12} className="text-muted-foreground" animate />
                Syncing...
              </>
            ) : (
              <>
                <LoaderIcon size={12} className="text-muted-foreground" />
                Sync
              </>
            )}
          </button>

          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${repo.reviews_enabled ? 'bg-success' : 'bg-muted-foreground'}`} />
            <span className="text-xs text-muted-foreground">
              {repo.reviews_enabled ? 'Active' : 'Off'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function RepositoriesPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  
  const [syncingRepoId, setSyncingRepoId] = useState<string | null>(null);
  const [configuringRepoId, setConfiguringRepoId] = useState<string | null>(null);
  const [isSyncingAll, setIsSyncingAll] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [configRepo, setConfigRepo] = useState<Repository | null>(null);
  const [availableModels, setAvailableModels] = useState<Record<string, ModelMetadata[]>>({});
  
  const { data: repos = [], isLoading: reposLoading, error: reposError } = useQuery({
    queryKey: ['repositories'],
    queryFn: api.getRepositories,
    refetchInterval: 5000,
  });

  const { data: apiKeys = [] } = useQuery({
    queryKey: ['api-keys'],
    queryFn: api.getApiKeys,
  });

  const handleConfigure = async (repo: Repository) => {
    setConfiguringRepoId(repo.id);
    try {
      const models = await api.getAvailableModels();
      setAvailableModels(models);
      setConfigRepo(repo);
    } catch (err: any) {
      toast({
        title: 'Failed to load models',
        description: err.response?.data?.detail || err.message,
        type: 'error',
      });
    } finally {
      setConfiguringRepoId(null);
    }
  };

  const handleSaveConfig = async (config: { assigned_provider?: string; assigned_model?: string; assigned_key_id?: string; reviews_enabled?: boolean }) => {
    if (!configRepo) return;
    await api.updateRepositoryConfig(configRepo.id, config);
    queryClient.invalidateQueries({ queryKey: ['repositories'] });
    toast({
      title: 'Configuration saved',
      type: 'success',
    });
  };

  const handleSync = async (id: string) => {
    setSyncingRepoId(id);
    try {
      const result = await api.syncRepository(id);
      toast({ title: 'Sync completed', description: result.message, type: 'success' });
      queryClient.invalidateQueries({ queryKey: ['repositories'] });
    } catch (err: any) {
      toast({
        title: 'Sync failed',
        description: err.response?.data?.detail || err.message,
        type: 'error',
      });
    } finally {
      setSyncingRepoId(null);
    }
  };

  const handleSyncAll = async () => {
    setIsSyncingAll(true);
    try {
      const result = await api.syncAllRepositories();
      toast({ title: 'Global sync completed', description: result.message, type: 'success' });
      queryClient.invalidateQueries({ queryKey: ['repositories'] });
    } catch (err: any) {
      toast({
        title: 'Global sync failed',
        description: err.response?.data?.detail || err.message,
        type: 'error',
      });
    } finally {
      setIsSyncingAll(false);
    }
  };

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="flex items-start justify-between mb-8 flex-wrap gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">Repositories</h1>
          <p className="text-muted-foreground mt-1 text-sm">Connected repositories from your GitHub App installation.</p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleSyncAll}
            disabled={isSyncingAll}
            className="flex items-center gap-2 px-4 py-2 bg-brand hover:bg-brand-hover disabled:opacity-50 text-brand-foreground rounded-lg text-sm font-semibold transition-colors cursor-pointer"
          >
            {isSyncingAll ? (
              <>
                <LoaderIcon size={14} className="text-brand-foreground" animate />
                Syncing...
              </>
            ) : (
              <>
                <LoaderIcon size={14} className="text-brand-foreground" />
                Sync from GitHub
              </>
            )}
          </button>
        </div>
      </div>

      {reposError && (
        <div className="mb-6 p-4 bg-error/10 border border-error/20 rounded-lg flex items-center gap-3">
          <TriangleAlertIcon size={20} className="text-error" />
          <p className="text-sm text-error">Failed to load repositories.</p>
        </div>
      )}

      {/* Search Bar */}
      {repos.length > 0 && (
        <div className="mb-6 max-w-md">
          <label htmlFor="repo-search" className="sr-only">Search repositories</label>
          <input
            id="repo-search"
            type="text"
            placeholder="Search repositories by name, description, or language..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full h-10 px-4 py-2 bg-surface-1 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/50 transition-colors"
          />
        </div>
      )}

      {reposLoading ? (
        <SkeletonList count={2} height="h-28" />
      ) : repos.length === 0 ? (
        <EmptyState
          icon={<FolderIcon size={32} />}
          title="No repositories connected"
          description="Install the Revora GitHub App and select repositories to start getting AI code reviews."
          action={
            <a
              href="https://github.com/apps"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-brand hover:bg-brand-hover text-brand-foreground rounded-lg text-sm font-medium transition-colors"
            >
              Install GitHub App
            </a>
          }
        />
      ) : (
        (() => {
          const filteredRepos = repos.filter((repo) => {
            const query = searchQuery.toLowerCase();
            const name = (repo.name || '').toLowerCase();
            const fullName = (repo.full_name || '').toLowerCase();
            const desc = (repo.description || '').toLowerCase();
            const lang = (repo.language || '').toLowerCase();
            return name.includes(query) || fullName.includes(query) || desc.includes(query) || lang.includes(query);
          });

          if (filteredRepos.length === 0) {
            return (
              <EmptyState
                icon={<FolderIcon size={32} />}
                title="No matching repositories"
                description="Try adjusting your search terms."
              />
            );
          }

          return (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {filteredRepos.map((repo) => (
                <RepositoryCard
                  key={repo.id}
                  repo={repo}
                  syncingRepoId={syncingRepoId}
                  configuringRepoId={configuringRepoId}
                  handleSync={handleSync}
                  onConfigure={handleConfigure}
                  apiKeys={apiKeys}
                />
              ))}
            </div>
          );
        })()
      )}

      {/* Config Modal */}
      {configRepo && (
        <ConfigModal
          repo={configRepo}
          availableModels={availableModels}
          apiKeys={apiKeys}
          onClose={() => setConfigRepo(null)}
          onSave={handleSaveConfig}
        />
      )}
    </div>
  );
}
