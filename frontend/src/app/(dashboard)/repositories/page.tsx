'use client';

import { useEffect, useState } from 'react';
import { api, Repository } from '@/lib/api';
import Link from 'next/link';

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
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[lang] ?? 'bg-zinc-800 text-zinc-400'}`}>
      {lang}
    </span>
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
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex items-start justify-between mb-8 flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Repositories</h1>
          <p className="text-zinc-400 mt-1.5">Connected repositories from your GitHub App installation.</p>
        </div>
        
        <div className="flex items-center gap-3">
          {syncMessage && (
            <div className="px-4 py-2 rounded-xl bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 text-sm animate-fade-in">
              {syncMessage}
            </div>
          )}

          <button
            onClick={handleSyncAll}
            disabled={isSyncingAll}
            className="flex items-center gap-2 px-4 py-2.5 bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50 text-white rounded-lg text-sm font-semibold transition-colors shadow-lg cursor-pointer"
          >
            {isSyncingAll ? (
              <>
                <div className="w-4 h-4 border border-white border-t-transparent rounded-full animate-spin" />
                Syncing list...
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 7.89M9 11l3-3 3 3m-3-3v12" />
                </svg>
                Sync from GitHub
              </>
            )}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-36 rounded-2xl bg-zinc-950 border border-white/5 animate-pulse" />
          ))}
        </div>
      ) : repos.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/10 p-20 text-center">
          <div className="w-16 h-16 rounded-full bg-zinc-900 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-zinc-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
          </div>
          <p className="text-zinc-300 font-semibold text-lg">No repositories connected</p>
          <p className="text-zinc-500 text-sm mt-2 max-w-sm mx-auto">
            Install the Revora GitHub App and select repositories to start getting AI code reviews.
          </p>
          <div className="flex justify-center gap-4 mt-6">
            <a
              href="https://github.com/apps"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg text-sm font-medium transition-colors"
            >
              Install GitHub App
            </a>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {repos.map((repo) => (
            <div
              key={repo.id}
              className="rounded-2xl border border-white/5 bg-zinc-950 hover:border-indigo-500/25 transition-all duration-200 p-6 group flex flex-col justify-between"
            >
              <div>
                <div className="flex items-start justify-between mb-3 gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <svg className="w-5 h-5 text-zinc-400 group-hover:text-indigo-400 transition-colors shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                    </svg>
                    <span className="font-semibold text-white truncate">{repo.full_name}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <LangBadge lang={repo.language} />
                    {repo.is_private && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-zinc-800 text-zinc-400">
                        Private
                      </span>
                    )}
                  </div>
                </div>

                {repo.description && (
                  <p className="text-zinc-500 text-sm mb-4 line-clamp-2">{repo.description}</p>
                )}
              </div>

              <div className="flex items-center justify-between mt-4 pt-4 border-t border-white/5">
                <div className="flex items-center gap-4 text-sm text-zinc-500">
                  <span className="flex items-center gap-1.5">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2" />
                    </svg>
                    {repo.total_reviews} reviews
                  </span>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    disabled={syncingRepoId !== null}
                    onClick={() => handleSync(repo.id)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 hover:bg-white/10 text-zinc-300 hover:text-white rounded-lg text-xs font-medium transition-all cursor-pointer border border-white/5 disabled:opacity-50"
                  >
                    {syncingRepoId === repo.id ? (
                      <>
                        <div className="w-3.5 h-3.5 border border-zinc-400 border-t-transparent rounded-full animate-spin" />
                        Syncing...
                      </>
                    ) : (
                      <>
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 7.89M9 11l3-3 3 3m-3-3v12" />
                        </svg>
                        Sync Historical Reviews
                      </>
                    )}
                  </button>

                  <div className="flex items-center gap-1.5">
                    <div className={`w-2 h-2 rounded-full ${repo.reviews_enabled ? 'bg-emerald-400' : 'bg-zinc-600'}`} />
                    <span className="text-xs text-zinc-500">
                      {repo.reviews_enabled ? 'Active' : 'Disabled'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
