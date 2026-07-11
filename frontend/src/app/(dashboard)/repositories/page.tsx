'use client';

import { useEffect, useState, useRef } from 'react';
import { api, Repository } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { FolderIcon, ClipboardIcon } from '@animateicons/react/lucide';
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

function RepositoryCard({ repo, syncingRepoId, handleSync }: { repo: Repository; syncingRepoId: string | null; handleSync: (id: string) => void }) {
  const folderRef = useRef<any>(null);
  const reviewsRef = useRef<any>(null);

  return (
    <div
      onMouseEnter={() => {
        folderRef.current?.startAnimation();
        reviewsRef.current?.startAnimation();
      }}
      onMouseLeave={() => {
        folderRef.current?.stopAnimation();
        reviewsRef.current?.stopAnimation();
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
      </div>

      <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <ClipboardIcon ref={reviewsRef} size={14} isAnimated={false} />
            {repo.total_reviews} reviews
          </span>
        </div>

        <div className="flex items-center gap-2.5">
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
                Sync Reviews
              </>
            )}
          </button>

          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${repo.reviews_enabled ? 'bg-success' : 'bg-muted-foreground'}`} />
            <span className="text-xs text-muted-foreground">
              {repo.reviews_enabled ? 'Active' : 'Disabled'}
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

  const fetchRepos = () => {
    api.getRepositories().then(setRepos).finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchRepos();
  }, []);

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
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {repos.map((repo) => (
            <RepositoryCard
              key={repo.id}
              repo={repo}
              syncingRepoId={syncingRepoId}
              handleSync={handleSync}
            />
          ))}
        </div>
      )}
    </div>
  );
}
