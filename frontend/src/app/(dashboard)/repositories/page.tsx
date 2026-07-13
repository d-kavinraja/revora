'use client';

import { useEffect, useState, useRef } from 'react';
import { api, Repository } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { FolderIcon, ClipboardIcon, SettingsIcon, XIcon } from '@animateicons/react/lucide';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonList } from '@/components/shared/skeleton';

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
  onClose,
  onSave,
}: {
  repo: Repository;
  availableModels: Record<string, string[]>;
  onClose: () => void;
  onSave: (config: { assigned_provider?: string; assigned_model?: string; reviews_enabled?: boolean }) => void;
}) {
  const providers = Object.keys(availableModels);
  const [selectedProvider, setSelectedProvider] = useState(repo.settings?.assigned_provider || (providers[0] ?? ''));
  const [selectedModel, setSelectedModel] = useState(repo.settings?.assigned_model || '');
  const [reviewsEnabled, setReviewsEnabled] = useState(repo.reviews_enabled);
  const [saving, setSaving] = useState(false);
  const settingsRef = useRef<any>(null);

  const models = availableModels[selectedProvider] || [];

  useEffect(() => {
    if (providers.length > 0 && !selectedProvider) {
      const initialProvider = repo.settings?.assigned_provider || providers[0];
      setSelectedProvider(initialProvider);
      const initialModels = availableModels[initialProvider] || [];
      setSelectedModel(repo.settings?.assigned_model || initialModels[0] || '');
    }
  }, [availableModels, providers, repo.settings?.assigned_provider, repo.settings?.assigned_model]);

  useEffect(() => {
    if (selectedProvider && models.length > 0 && !models.includes(selectedModel)) {
      setSelectedModel(models[0]);
    }
  }, [selectedProvider, models, selectedModel]);

  useEffect(() => {
    settingsRef.current?.startAnimation?.();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    await onSave({
      assigned_provider: selectedProvider || undefined,
      assigned_model: selectedModel || undefined,
      reviews_enabled: reviewsEnabled,
    });
    setSaving(false);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-md bg-surface-1 border border-border rounded-xl shadow-2xl p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-lg font-semibold text-foreground">Configure Model</h3>
            <p className="text-xs text-muted-foreground mt-0.5">{repo.full_name}</p>
          </div>
          <button onClick={onClose} className="p-1 rounded text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
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
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Provider</label>
              <select
                value={selectedProvider}
                onChange={(e) => setSelectedProvider(e.target.value)}
                className="w-full mt-1.5 px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 cursor-pointer"
              >
                {providers.map((p) => (
                  <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
                ))}
              </select>
            </div>

            {/* Model Selector */}
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Model</label>
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full mt-1.5 px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 cursor-pointer"
              >
                {models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>

            {/* Reviews Toggle */}
            <div className="flex items-center justify-between py-2">
              <div>
                <label className="text-sm font-medium text-foreground">Reviews Enabled</label>
                <p className="text-xs text-muted-foreground">Automatically review pull requests</p>
              </div>
              <button
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
  handleSync,
  onConfigure,
}: {
  repo: Repository;
  syncingRepoId: string | null;
  handleSync: (id: string) => void;
  onConfigure: (repo: Repository) => void;
}) {
  const folderRef = useRef<any>(null);
  const reviewsRef = useRef<any>(null);
  const settingsRef = useRef<any>(null);

  const assignedModel = repo.settings?.assigned_model;
  const assignedProvider = repo.settings?.assigned_provider;

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
      className="rounded-xl border border-border bg-surface-1 hover:border-brand/25 transition-all duration-150 p-5 group flex flex-col justify-between"
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
            <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-brand/10 text-brand border border-brand/20">
              {assignedProvider}: {assignedModel}
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
            onClick={() => onConfigure(repo)}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors cursor-pointer"
            title="Configure model"
          >
            <SettingsIcon ref={settingsRef} size={14} isAnimated={false} />
          </button>

          <button
            disabled={syncingRepoId !== null}
            onClick={() => handleSync(repo.id)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-white/[0.04] hover:bg-white/[0.08] text-muted-foreground hover:text-foreground rounded-lg text-xs font-medium transition-colors cursor-pointer border border-border disabled:opacity-50"
          >
            {syncingRepoId === repo.id ? (
              <>
                <LoaderIcon size={12} className="text-muted-foreground" />
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
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncingRepoId, setSyncingRepoId] = useState<string | null>(null);
  const [isSyncingAll, setIsSyncingAll] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [configRepo, setConfigRepo] = useState<Repository | null>(null);
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});

  const fetchRepos = () => {
    api.getRepositories().then(setRepos).finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchRepos();
  }, []);

  const handleConfigure = async (repo: Repository) => {
    try {
      const models = await api.getAvailableModels();
      setAvailableModels(models);
      setConfigRepo(repo);
    } catch {
      setAvailableModels({});
      setConfigRepo(repo);
    }
  };

  const handleSaveConfig = async (config: { assigned_provider?: string; assigned_model?: string; reviews_enabled?: boolean }) => {
    if (!configRepo) return;
    try {
      const updated = await api.updateRepositoryConfig(configRepo.id, config);
      setRepos((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      setSyncMessage('Configuration saved');
      setTimeout(() => setSyncMessage(null), 3000);
    } catch (err: any) {
      setSyncMessage(err.response?.data?.detail || 'Failed to save configuration');
      setTimeout(() => setSyncMessage(null), 3000);
    }
  };

  const handleSync = async (id: string) => {
    setSyncingRepoId(id);
    setSyncMessage(null);
    try {
      const result = await api.syncRepository(id);
      setSyncMessage(result.message);
      fetchRepos();
      setTimeout(() => setSyncMessage(null), 5000);
    } catch (err: any) {
      console.error(err);
      setSyncMessage(err.response?.data?.detail || 'Sync failed.');
      setTimeout(() => setSyncMessage(null), 5000);
    } finally {
      setSyncingRepoId(null);
    }
  };

  const handleSyncAll = async () => {
    setIsSyncingAll(true);
    setSyncMessage(null);
    try {
      const result = await api.syncAllRepositories();
      setSyncMessage(result.message);
      fetchRepos();
      setTimeout(() => setSyncMessage(null), 5000);
    } catch (err: any) {
      console.error(err);
      setSyncMessage(err.response?.data?.detail || 'Global sync failed.');
      setTimeout(() => setSyncMessage(null), 5000);
    } finally {
      setIsSyncingAll(false);
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto">
      <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">Repositories</h1>
          <p className="text-muted-foreground mt-1 text-sm">Connected repositories from your GitHub App installation.</p>
        </div>

        <div className="flex items-center gap-3">
          {syncMessage && (
            <div className="px-3 py-1.5 rounded-lg bg-brand/10 text-brand border border-brand/20 text-sm animate-fade-in">
              {syncMessage}
            </div>
          )}

          <button
            onClick={handleSyncAll}
            disabled={isSyncingAll}
            className="flex items-center gap-2 px-4 py-2 bg-brand hover:bg-brand-hover disabled:opacity-50 text-brand-foreground rounded-lg text-sm font-semibold transition-colors cursor-pointer"
          >
            {isSyncingAll ? (
              <>
                <LoaderIcon size={14} className="text-brand-foreground" />
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

      {/* Search Bar */}
      {repos.length > 0 && (
        <div className="mb-6 max-w-md">
          <input
            type="text"
            placeholder="Search repositories by name, description, or language..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full px-3.5 py-2 bg-surface-1 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/50 transition-colors"
          />
        </div>
      )}

      {loading ? (
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
                  handleSync={handleSync}
                  onConfigure={handleConfigure}
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
          onClose={() => setConfigRepo(null)}
          onSave={handleSaveConfig}
        />
      )}
    </div>
  );
}
