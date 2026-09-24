'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import Image from 'next/image';
import { api, Repository, ApiKey, ModelMetadata, RepoGithubStats } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { FolderIcon, ClipboardIcon, SettingsIcon, XIcon, TriangleAlertIcon, CircleCheckIcon } from '@animateicons/react/lucide';
import { Star, AlertTriangle, Lock, RefreshCw, CheckCircle2, ShieldAlert, Power, GitFork, CircleDot, Users, Eye, ExternalLink } from 'lucide-react';
import { EmptyState } from '@/components/shared/empty-state';
import { SkeletonList } from '@/components/shared/skeleton';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/components/ui/toaster';
import { ProviderIcon } from '@/components/ui/provider-icon';

const LANG_COLORS: Record<string, string> = {
  Python: '#3572A5',
  TypeScript: '#2b7489',
  JavaScript: '#f1e05a',
  Go: '#00ADD8',
  Rust: '#dea584',
  Java: '#b07219',
  'C++': '#f34b7d',
  C: '#555555',
  Ruby: '#701516',
  Swift: '#ffac45',
  Kotlin: '#A97BFF',
  PHP: '#4F5D95',
  'C#': '#178600',
  Shell: '#89e051',
  Dart: '#00B4AB',
  Scala: '#c22d40',
};

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

function timeAgo(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatCount(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function GithubRepoStats({ repoId }: { repoId: string }) {
  const { data, isLoading } = useQuery<RepoGithubStats>({
    queryKey: ['repo-github-stats', repoId],
    queryFn: () => api.getRepoGithubStats(repoId),
    staleTime: 5 * 60 * 1000, // cache for 5 minutes
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-4 text-xs text-muted-foreground animate-pulse">
        {[1,2,3,4].map(i => (
          <div key={i} className="flex items-center gap-1">
            <div className="w-3 h-3 rounded-full bg-muted-foreground/20" />
            <div className="w-6 h-3 rounded bg-muted-foreground/20" />
          </div>
        ))}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
      {data.contributors > 0 && (
        <span className="flex items-center gap-1 hover:text-foreground transition-colors" title="Contributors">
          <Users size={13} className="text-muted-foreground" />
          {formatCount(data.contributors)}
        </span>
      )}
      <span className="flex items-center gap-1 hover:text-foreground transition-colors" title="Open Issues">
        <CircleDot size={13} className="text-muted-foreground" />
        {formatCount(data.open_issues)}
      </span>
      <span className="flex items-center gap-1 hover:text-foreground transition-colors" title="Stars">
        <Star size={13} className="text-amber-600 fill-amber-600/50" />
        {formatCount(data.stars)}
      </span>
      <span className="flex items-center gap-1 hover:text-foreground transition-colors" title="Forks">
        <GitFork size={13} className="text-muted-foreground" />
        {formatCount(data.forks)}
      </span>
      {data.homepage && (
        <a
          href={data.homepage}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-brand/70 hover:text-brand transition-colors"
          title="Homepage"
          onClick={(e) => e.stopPropagation()}
        >
          <ExternalLink size={11} />
          Website
        </a>
      )}
    </div>
  );
}

function GithubRepoAvatar({ repoId, fallbackName }: { repoId: string; fallbackName: string }) {
  const { data } = useQuery<RepoGithubStats>({
    queryKey: ['repo-github-stats', repoId],
    queryFn: () => api.getRepoGithubStats(repoId),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const initials = fallbackName.split('/')[0]?.charAt(0)?.toUpperCase() ?? '?';

  if (!data?.owner_avatar_url) {
    return (
      <div className="w-12 h-12 rounded-xl bg-surface-2 border border-border flex items-center justify-center text-base font-bold text-muted-foreground shrink-0 select-none">
        {initials}
      </div>
    );
  }

  return (
    <div className="w-12 h-12 rounded-xl overflow-hidden border border-border shrink-0">
      <img
        src={data.owner_avatar_url}
        alt={`${fallbackName.split('/')[0]} avatar`}
        className="w-full h-full object-cover"
        loading="lazy"
      />
    </div>
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
  
  const matchProvider = (p1: string, p2: string) => {
    const norm1 = (p1 || '').toLowerCase().replace('_nim', '');
    const norm2 = (p2 || '').toLowerCase().replace('_nim', '');
    return norm1 === norm2;
  };

  const providerKeys = apiKeys.filter(k => matchProvider(k.provider, selectedProvider) && k.is_valid);

  const [selectedKeyId, setSelectedKeyId] = useState(() => {
    const saved = repo.settings?.assigned_key_id;
    return (saved && providerKeys.some(k => k.id === saved)) ? saved : (providerKeys[0]?.id ?? '');
  });

  const allModels = availableModels[selectedProvider] || availableModels[selectedProvider === 'nvidia' ? 'nvidia_nim' : 'nvidia'] || [];

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
    const keys = apiKeys.filter(k => matchProvider(k.provider, selectedProvider) && k.is_valid);
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

  const isReviewActive = repo.active_review_status === 'queued' || repo.active_review_status === 'pending' || repo.active_review_status === 'running';

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
          <div className="flex items-center gap-3">
            {selectedProvider && (
              <div className="w-10 h-10 rounded-xl bg-surface-2 border border-border flex items-center justify-center shrink-0">
                <ProviderIcon slug={selectedProvider} size={20} />
              </div>
            )}
            <div>
              <h3 id="modal-title" className="text-lg font-semibold text-foreground flex items-center gap-2">
                Configure Model
              </h3>
              <p className="text-xs text-muted-foreground mt-0.5">{repo.full_name}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded text-muted-foreground hover:text-foreground transition-colors cursor-pointer" aria-label="Close dialog">
            <XIcon size={18} />
          </button>
        </div>

        {isReviewActive && (
          <div className="mb-4 p-3 rounded-lg bg-amber-500/15 border border-amber-500/30 flex items-start gap-2.5 text-xs text-amber-400 leading-relaxed">
            <Lock size={16} className="shrink-0 mt-0.5 text-amber-400" />
            <div>
              <strong>Configuration Locked:</strong> A Pull Request review is currently <strong>{repo.active_review_status}</strong> on this repository. Model settings cannot be changed until the review completes.
            </div>
          </div>
        )}

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
              <div className="relative flex items-center mt-1.5">
                <div className="absolute left-3 pointer-events-none flex items-center justify-center">
                  <ProviderIcon slug={selectedProvider} size={16} />
                </div>
                <select
                  id="provider-select"
                  value={selectedProvider}
                  disabled={isReviewActive}
                  onChange={(e) => setSelectedProvider(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {providers.map((p) => {
                    const labelName = (p === 'nvidia' || p === 'nvidia_nim') ? 'NVIDIA NIM' : p.charAt(0).toUpperCase() + p.slice(1);
                    return (
                      <option key={p} value={p}>{labelName}</option>
                    );
                  })}
                </select>
              </div>
            </div>

            {/* API Key Selector */}
            {providerKeys.length > 0 && (
              <div>
                <label htmlFor="key-select" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">API Key</label>
                <select
                  id="key-select"
                  value={selectedKeyId}
                  disabled={isReviewActive}
                  onChange={(e) => setSelectedKeyId(e.target.value)}
                  className="w-full mt-1.5 px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
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
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor="model-select" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Model</label>
                <div className="flex gap-2">
                  <label className="flex items-center gap-1 cursor-pointer text-[11px] text-muted-foreground">
                    <input type="checkbox" checked={showPreview} disabled={isReviewActive} onChange={(e) => setShowPreview(e.target.checked)} className="accent-brand rounded-sm" /> Preview
                  </label>
                  <label className="flex items-center gap-1 cursor-pointer text-[11px] text-muted-foreground">
                    <input type="checkbox" checked={showDeprecated} disabled={isReviewActive} onChange={(e) => setShowDeprecated(e.target.checked)} className="accent-brand rounded-sm" /> Deprecated
                  </label>
                  <label className="flex items-center gap-1 cursor-pointer text-[11px] text-muted-foreground">
                    <input type="checkbox" checked={showUnavailable} disabled={isReviewActive} onChange={(e) => setShowUnavailable(e.target.checked)} className="accent-brand rounded-sm" /> Unavailable
                  </label>
                </div>
              </div>
              <div className="relative flex items-center">
                <div className="absolute left-3 pointer-events-none flex items-center justify-center">
                  <ProviderIcon slug={selectedProvider} size={16} />
                </div>
                <select
                  id="model-select"
                  value={selectedModel}
                  disabled={isReviewActive}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {models.map((m, idx) => {
                    let badge = '';
                    if (!m.accessible) badge = ' [Unavailable]';
                    else if (idx < 5) badge = ' [Recommended]';
                    else if (m.deprecated) badge = ' [Deprecated]';
                    else if (m.preview || m.experimental) badge = ' [Preview]';
                    else if (m.enterprise_only) badge = ' [Enterprise]';
                    else badge = ' [High Load Server]';
                    
                    return (
                      <option key={m.model_name} value={m.model_name} disabled={!m.accessible} title={!m.accessible ? 'This model is inaccessible with your current API key permissions.' : ''}>
                        {m.model_name}{badge}
                      </option>
                    );
                  })}
                </select>
              </div>

              {/* Dynamic Model Status Banner */}
              {selectedModel && (!isReviewActive) && (() => {
                const selectedIdx = models.findIndex(m => m.model_name === selectedModel);
                if (selectedIdx >= 0 && selectedIdx < 5) {
                  return (
                    <div className="mt-2.5 p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center gap-2 text-xs text-emerald-400">
                      <Star size={14} className="shrink-0 text-amber-400 fill-amber-400" />
                      <span><strong>Recommended Model:</strong> High throughput, optimized for fast code reviews with low latency.</span>
                    </div>
                  );
                } else if (selectedIdx >= 5) {
                  return (
                    <div className="mt-2.5 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-start gap-2 text-xs text-amber-400 leading-relaxed">
                      <AlertTriangle size={16} className="shrink-0 mt-0.5 text-amber-400" />
                      <div>
                        <strong>High Load Notice:</strong> Non-recommended models on open public API servers may experience server queue load, higher response latency, or timeouts. For fast reviews, select a Recommended model.
                      </div>
                    </div>
                  );
                }
                return null;
              })()}
            </div>

            {/* Reviews Toggle */}
            <div className="flex items-center justify-between py-2">
              <div>
                <label id="reviews-label" className="text-sm font-medium text-foreground">Reviews Enabled</label>
                <p className="text-xs text-muted-foreground">Automatically review pull requests</p>
              </div>
              <button
                role="switch"
                disabled={isReviewActive}
                aria-checked={reviewsEnabled}
                aria-labelledby="reviews-label"
                onClick={() => !isReviewActive && setReviewsEnabled(!reviewsEnabled)}
                className={`relative w-10 h-5 rounded-full transition-colors ${isReviewActive ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'} ${reviewsEnabled ? 'bg-brand' : 'bg-muted'}`}
              >
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${reviewsEnabled ? 'left-5.5 translate-x-0' : 'left-0.5'}`} />
              </button>
            </div>

            {/* Save Button */}
            <button
              onClick={handleSave}
              disabled={saving || !selectedModel || isReviewActive}
              className="w-full py-2.5 bg-brand hover:bg-brand-hover disabled:opacity-50 text-brand-foreground rounded-lg text-sm font-semibold transition-colors cursor-pointer disabled:cursor-not-allowed"
            >
              {isReviewActive ? (
                <span className="inline-flex items-center gap-2">
                  <Lock size={14} />
                  Configuration Locked (Review Active)
                </span>
              ) : saving ? 'Saving...' : 'Save Configuration'}
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

  const removed = repo.status === 'removed';

  const assignedModel = repo.settings?.assigned_model;
  const assignedProvider = repo.settings?.assigned_provider;
  const assignedKeyId = repo.settings?.assigned_key_id;
  const keyObj = apiKeys.find(k => k.id === assignedKeyId);
  const keyLabel = keyObj ? ` (${keyObj.label})` : '';

  const isReviewActive = repo.active_review_status === 'queued' || repo.active_review_status === 'pending' || repo.active_review_status === 'running';

  const [owner, repoName] = repo.full_name.split('/');
  const langColor = repo.language ? (LANG_COLORS[repo.language] ?? '#8b949e') : null;

  // Determine truthful sync status for display
  const syncState = repo.sync_state;
  const lastSyncedAt = repo.last_synced_at;
  const lastSyncCompletedAt = repo.last_sync?.completed_at;
  const syncCompletedAt = syncState?.completed_at ?? lastSyncCompletedAt ?? lastSyncedAt;

  const getSyncStatus = (): { label: string; variant: 'danger' | 'warning' | 'info' | 'success' | 'neutral' } => {
    if (!syncState) {
      if (lastSyncedAt) return { label: `Synced ${timeAgo(lastSyncedAt)}`, variant: 'success' };
      return { label: 'Never Synced', variant: 'neutral' };
    }

    switch (syncState.status) {
      case 'failed': return { label: `Sync Failed: ${syncState.error?.slice(0, 40) ?? 'Unknown error'}`, variant: 'danger' };
      case 'stale': return { label: 'Sync Stale', variant: 'warning' };
      case 'running': return { label: 'Syncing…', variant: 'info' };
      case 'partial': return { label: 'Sync Partial', variant: 'warning' };
      case 'queued': return { label: 'Sync Queued', variant: 'info' };
      case 'success': {
        const prsFound = syncState?.prs_found ?? 0;
        if (prsFound === 0) return { label: `Synced ${timeAgo(syncCompletedAt)} — 0 open PRs`, variant: 'success' };
        return { label: `Synced ${timeAgo(syncCompletedAt)} — ${prsFound} open PRs`, variant: 'success' };
      }
      default: return { label: 'Unknown', variant: 'neutral' };
    }
  };

  const syncStatus = getSyncStatus();

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
      className={`repo-card-light cursor-target rounded-xl border border-border bg-surface-1 hover:border-brand/25 hover:shadow-lg hover:shadow-brand/5 transition-all duration-200 group flex flex-col ${removed ? 'opacity-75 hover:border-border' : ''}`}
    >
      {/* Card Header */}
      <div className="p-5 flex-1 flex flex-col gap-3">
        {/* Top Row: owner avatar + repo name */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            {!removed && <GithubRepoAvatar repoId={repo.id} fallbackName={repo.full_name} />}
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-xs text-muted-foreground font-mono">{owner}/</span>
                <span className="font-bold text-foreground text-sm leading-tight truncate">{repoName}</span>
              </div>
              <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                {repo.is_private && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-muted/60 text-muted-foreground border border-border/50">
                    Private
                  </span>
                )}
                {repo.status === 'permission_required' && (
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-500/15 text-amber-700 border border-amber-500/30">
                    <ShieldAlert className="w-2.5 h-2.5" />
                    Permission Required
                  </span>
                )}
                {isReviewActive && (
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-500/15 text-amber-700 border border-amber-500/30 animate-pulse">
                    <RefreshCw className="w-2.5 h-2.5 animate-spin" />
                    Review {repo.active_review_status === 'pending' ? 'Pending' : 'Running'}
                  </span>
                )}
              </div>
            </div>
          </div>
          {/* Reviews count badge */}
          <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-surface-2 border border-border text-xs text-muted-foreground shrink-0" title={`${repo.total_reviews} reviews`}>
            <ClipboardIcon ref={reviewsRef} size={12} isAnimated={false} />
            <span>{repo.total_reviews}</span>
          </div>
        </div>

        {/* Description */}
        {repo.description ? (
          <p className="text-muted-foreground text-xs leading-relaxed line-clamp-2">{repo.description}</p>
        ) : (
          <p className="text-muted-foreground/70 text-xs italic">No description</p>
        )}

        {/* Removed notice */}
        {removed && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-muted text-muted-foreground border border-border self-start">
            Removed {timeAgo(repo.removed_at) ?? ''} — history preserved
          </span>
        )}

        {/* Assigned model */}
        {assignedModel && !removed && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-brand/10 text-brand border border-brand/20 self-start max-w-full truncate">
            {assignedProvider && <ProviderIcon slug={assignedProvider} size={12} />}
            {assignedProvider && (assignedProvider === 'nvidia' || assignedProvider === 'nvidia_nim' ? 'NVIDIA NIM' : (assignedProvider.charAt(0).toUpperCase() + assignedProvider.slice(1)))}: {assignedModel}{keyLabel}
          </span>
        )}

        {/* GitHub Stats Row */}
        {!removed && <GithubRepoStats repoId={repo.id} />}

        {/* Language + topics row */}
        {repo.language && (
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span
                className="w-3 h-3 rounded-full shrink-0"
                style={{ backgroundColor: langColor ?? '#8b949e' }}
              />
              {repo.language}
            </span>
          </div>
        )}
      </div>

      {/* Card Footer - Revora Controls */}
      {!removed && (
        <div className="flex items-center justify-between px-5 py-3 border-t border-border bg-surface-2/30 rounded-b-xl">
          {/* Left: sync status */}
          <div className="text-xs">
            {syncStatus.variant === 'danger' && (
              <span className="flex items-center gap-1.5 text-red-400">
                <AlertTriangle className="w-3 h-3" />
                {syncStatus.label}
              </span>
            )}
            {syncStatus.variant === 'warning' && (
              <span className="flex items-center gap-1.5 text-amber-400">
                <AlertTriangle className="w-3 h-3" />
                {syncStatus.label}
              </span>
            )}
            {syncStatus.variant === 'info' && (
              <span className="flex items-center gap-1.5 text-blue-400">
                <LoaderIcon size={12} className="animate-spin" />
                {syncStatus.label}
              </span>
            )}
            {syncStatus.variant === 'success' && (
              <span className="flex items-center gap-1.5 text-emerald-400">
                <CheckCircle2 className="w-3 h-3" />
                {syncStatus.label}
              </span>
            )}
            {syncStatus.variant === 'neutral' && (
              <span className="flex items-center gap-1.5 text-muted-foreground/70 italic">
                <RefreshCw className="w-3 h-3" />
                {syncStatus.label}
              </span>
            )}
          </div>

          {/* Right: Controls */}
          <div className="flex items-center gap-2">
            {/* Active indicator */}
            <div className="flex items-center gap-1.5">
              <div className={`w-1.5 h-1.5 rounded-full ${repo.reviews_enabled ? 'bg-success' : 'bg-muted-foreground'}`} />
              <span className="text-xs text-muted-foreground hidden sm:inline">
                {repo.reviews_enabled ? 'Active' : 'Off'}
              </span>
            </div>

            {/* Configure button */}
            <button
              disabled={configuringRepoId === repo.id || syncingRepoId === repo.id || isReviewActive}
              onClick={() => onConfigure(repo)}
              className={`p-1.5 rounded-lg transition-colors focus-visible:outline-2 focus-visible:outline-brand/60 focus-visible:outline-offset-1 ${isReviewActive ? 'opacity-40 cursor-not-allowed text-muted-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-white/[0.04] cursor-pointer disabled:opacity-50'}`}
              title={isReviewActive ? `Model configuration is locked while a review is ${repo.active_review_status} on this repository.` : 'Configure model'}
            >
              {configuringRepoId === repo.id ? (
                <LoaderIcon size={14} className="text-muted-foreground" animate />
              ) : (
                <SettingsIcon ref={settingsRef} size={14} isAnimated={false} />
              )}
            </button>

            {/* Sync button */}
            <button
              disabled={syncingRepoId !== null}
              onClick={() => handleSync(repo.id)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 bg-white/[0.04] hover:bg-white/[0.08] text-muted-foreground hover:text-foreground rounded-lg text-xs font-medium transition-colors cursor-pointer border border-border disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-brand/60 focus-visible:outline-offset-1"
            >
              {syncingRepoId === repo.id ? (
                <>
                  <LoaderIcon size={12} className="text-muted-foreground" animate />
                  Syncing...
                </>
              ) : (
                <>
                  <RefreshCw size={12} className="text-muted-foreground" />
                  Sync
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {removed && (
        <div className="px-5 py-3 border-t border-border bg-surface-2/30 rounded-b-xl">
          <span className="text-xs font-medium text-muted-foreground">Not receiving reviews</span>
        </div>
      )}
    </div>
  );
}


export default function RepositoriesPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  
  const [view, setView] = useState<'active' | 'removed'>('active');
  const [syncingRepoId, setSyncingRepoId] = useState<string | null>(null);
  const [configuringRepoId, setConfiguringRepoId] = useState<string | null>(null);
  const [isSyncingAll, setIsSyncingAll] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [configRepo, setConfigRepo] = useState<Repository | null>(null);
  const [availableModels, setAvailableModels] = useState<Record<string, ModelMetadata[]>>({});
  
  const activeQuery = useQuery({
    queryKey: ['repositories', 'active'],
    queryFn: () => api.getRepositories(false),
    refetchInterval: 5000,
  });

  const removedQuery = useQuery({
    queryKey: ['repositories', 'removed'],
    queryFn: () => api.getRepositories(true),
    refetchInterval: 5000,
  });

  const repos = view === 'removed' ? (removedQuery.data ?? []) : (activeQuery.data ?? []);
  const reposLoading = view === 'removed' ? removedQuery.isLoading : activeQuery.isLoading;
  const reposError = view === 'removed' ? removedQuery.error : activeQuery.error;

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

  // Baseline timestamp captured when a background sync starts; the spinner
  // clears once the polled repository row shows a newer last-synced time.
  const [syncBaseline, setSyncBaseline] = useState<{ id: string; at: string | null } | null>(null);
  // Baselines for a global sync: every visible repository must advance.
  const [syncAllBaseline, setSyncAllBaseline] = useState<{ at: Record<string, string | null> } | null>(null);

  const handleSync = async (id: string) => {
    const repo = (activeQuery.data ?? []).find((r) => r.id === id);
    setSyncingRepoId(id);
    try {
      const result = await api.syncRepository(id);
      setSyncBaseline({ id, at: repo?.last_sync?.completed_at ?? repo?.last_synced_at ?? null });
      if (result.status === 'in_progress') {
        // Duplicate-sync guard fired server-side (double-click / refresh
        // resend): keep the spinner, do not restart the baseline.
        toast({ title: 'Sync already running', description: result.message, type: 'success' });
      } else {
        toast({ title: 'Sync started', description: result.message, type: 'success' });
      }
      queryClient.invalidateQueries({ queryKey: ['repositories'] });
      // Safety net: never leave the spinner stuck if the background pass
      // fails without updating the timestamp.
      setTimeout(() => {
        setSyncingRepoId((current) => (current === id ? null : current));
        setSyncBaseline((current) => (current?.id === id ? null : current));
      }, 180000);
    } catch (err: any) {
      toast({
        title: 'Sync failed',
        description: err.response?.data?.detail || err.message,
        type: 'error',
      });
      setSyncingRepoId(null);
      setSyncBaseline(null);
    }
  };

  // Refresh durability: the backend owns sync state (sync_state per repo).
  // After a browser refresh, React state is gone but the sync continues
  // server-side — re-attach the spinner to the still-running sync instead
  // of showing idle (and never fire a duplicate sync from here).
  useEffect(() => {
    if (syncingRepoId || syncBaseline) return;
    const running = (activeQuery.data ?? []).find((r) => r.sync_state?.status === 'running');
    if (running) {
      setSyncingRepoId(running.id);
      setSyncBaseline({
        id: running.id,
        at: running.last_sync?.completed_at ?? running.last_synced_at ?? null,
      });
    }
  }, [activeQuery.data, syncingRepoId, syncBaseline]);

  // Sync runs in the background: mark it complete once the repository row
  // (refetched every 5s) shows a newer last-synced timestamp, or the
  // backend sync_state reaches a terminal status (success/partial/failed).
  useEffect(() => {
    if (!syncBaseline) return;
    const repo = (activeQuery.data ?? []).find((r) => r.id === syncBaseline.id);
    if (!repo) return;
    const current = repo?.last_sync?.completed_at ?? repo?.last_synced_at ?? null;
    const stateStatus = repo?.sync_state?.status ?? null;
    const stateDone = stateStatus === 'success' || stateStatus === 'partial' || stateStatus === 'failed';
    if ((current && current !== syncBaseline.at) || stateDone) {
      setSyncBaseline(null);
      setSyncingRepoId(null);
      queryClient.invalidateQueries({ queryKey: ['repositories'] });
      if (stateStatus === 'failed') {
        toast({ title: 'Sync failed', description: repo?.sync_state?.error ?? undefined, type: 'error' });
      } else if (stateStatus === 'partial') {
        toast({ title: 'Sync completed with errors', description: repo?.sync_state?.error ?? undefined, type: 'error' });
      } else {
        toast({ title: 'Sync completed', type: 'success' });
      }
    }
  }, [activeQuery.data, syncBaseline, queryClient]);

  const handleSyncAll = async () => {
    const repos = activeQuery.data ?? [];
    const at: Record<string, string | null> = {};
    for (const r of repos) {
      at[r.id] = r.last_sync?.completed_at ?? r.last_synced_at ?? null;
    }
    setSyncAllBaseline({ at });
    setIsSyncingAll(true);
    try {
      const result = await api.syncAllRepositories();
      toast({ title: 'Global sync started', description: result.message, type: 'success' });
      queryClient.invalidateQueries({ queryKey: ['repositories'] });
      // Safety net for the background pass.
      setTimeout(() => {
        setIsSyncingAll(false);
        setSyncAllBaseline(null);
      }, 180000);
    } catch (err: any) {
      toast({
        title: 'Global sync failed',
        description: err.response?.data?.detail || err.message,
        type: 'error',
      });
      setIsSyncingAll(false);
      setSyncAllBaseline(null);
    }
  };

  // Global sync runs in the background: complete once every visible
  // repository row shows a newer last-synced timestamp.
  useEffect(() => {
    if (!syncAllBaseline) return;
    const repos = activeQuery.data ?? [];
    if (repos.length === 0) return;
    const allAdvanced = repos.every((r) => {
      const current = r.last_sync?.completed_at ?? r.last_synced_at ?? null;
      return current && current !== (syncAllBaseline.at[r.id] ?? null);
    });
    if (allAdvanced) {
      setSyncAllBaseline(null);
      setIsSyncingAll(false);
      queryClient.invalidateQueries({ queryKey: ['repositories'] });
      toast({ title: 'Global sync completed', type: 'success' });
    }
  }, [activeQuery.data, syncAllBaseline, queryClient]);

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
        <div className="mb-6 p-4 bg-error/10 border border-error/30 rounded-lg flex items-center gap-3">
          <TriangleAlertIcon size={20} className="text-error" />
          <p className="text-sm text-error">Failed to load repositories.</p>
        </div>
      )}

      {/* Tabs */}
      <div className="mb-6 flex items-center gap-2">
        <button
          onClick={() => setView('active')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer ${view === 'active' ? 'bg-brand/10 text-brand border border-brand/20' : 'bg-surface-1 border border-border text-muted-foreground hover:text-foreground'}`}
        >
          Active ({activeQuery.data?.length ?? 0})
        </button>
        <button
          onClick={() => setView('removed')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer ${view === 'removed' ? 'bg-brand/10 text-brand border border-brand/20' : 'bg-surface-1 border border-border text-muted-foreground hover:text-foreground'}`}
        >
          Removed ({removedQuery.data?.length ?? 0})
        </button>
      </div>

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
            className="w-full h-10 px-4 py-2 bg-surface-1 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand/60 transition-colors"
          />
        </div>
      )}

      {reposLoading ? (
        <SkeletonList count={2} height="h-28" />
      ) : repos.length === 0 ? (
        view === 'removed' ? (
          <EmptyState
            icon={<FolderIcon size={32} />}
            title="No removed repositories"
            description="Repositories removed from Revora appear here with their full review history preserved."
          />
        ) : (
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
        )
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
