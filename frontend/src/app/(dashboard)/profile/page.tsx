'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Settings, LogOut, ShieldCheck, CheckCircle2, GitPullRequest, GitFork, GitMerge, FileCode2, ExternalLink } from 'lucide-react';
import { useAuthStore } from '@/store/useAuthStore';
import { apiClient } from '@/lib/api';
import { ProviderIcon } from '@/components/ui/provider-icon';

export default function ProfilePage() {
  const router = useRouter();
  const { user, logout } = useAuthStore();
  
  const [stats, setStats] = useState<any>(null);
  const [providers, setProviders] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) {
      router.push('/login');
      return;
    }

    const fetchData = async () => {
      setLoading(true);
      try {
        const [statsRes, providersRes, keysRes] = await Promise.all([
          apiClient.get('/dashboard/stats').catch(() => ({ data: null })),
          apiClient.get('/providers').catch(() => ({ data: [] })),
          apiClient.get('/api-keys').catch(() => ({ data: [] }))
        ]);
        
        if (statsRes.data) setStats(statsRes.data);
        
        const allProviders = providersRes.data || [];
        const apiKeys = keysRes.data || [];
        
        // Find which providers have keys configured
        const activeSlugs = new Set(apiKeys.map((key: any) => key.provider));
        const activeProviders = allProviders.filter((p: any) => activeSlugs.has(p.slug));
        
        setProviders(activeProviders);
        
      } catch (err) {
        console.error('Error fetching profile data', err);
        setError('Unable to load profile data');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [user, router]);

  const handleLogout = () => {
    logout();
    router.push('/login');
  };

  if (!user) return null;

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-8 animate-in fade-in slide-in-from-bottom-4 duration-500 pb-24 text-foreground">
      {/* Navigation */}
      <div className="flex items-center justify-between mb-8">
        <Link 
          href="/dashboard" 
          className="cursor-target inline-flex items-center gap-2 text-sm font-semibold text-foreground hover:text-brand transition-colors group bg-surface-2 hover:bg-surface-3 px-4 py-2 rounded-lg border border-border"
        >
          <ArrowLeft size={16} className="group-hover:-translate-x-1 transition-transform" />
          Back to Dashboard
        </Link>
        <div className="flex items-center gap-3">
          <Link 
            href="/settings/usage"
            className="cursor-target p-2 text-foreground hover:text-brand rounded-full bg-surface-2 hover:bg-surface-3 border border-border transition-colors shadow-sm"
            title="Settings"
          >
            <Settings size={18} />
          </Link>
          <button 
            onClick={handleLogout}
            className="cursor-target p-2 text-foreground hover:text-error rounded-full bg-surface-2 hover:bg-error/10 border border-border transition-colors shadow-sm"
            title="Sign out"
          >
            <LogOut size={18} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        
        {/* Left Column (Identity & Revora Branding) */}
        <div className="md:col-span-1 space-y-6">
          
          {/* Identity Card */}
          <div className="rounded-xl border-2 border-border bg-surface-1 p-6 shadow-xl flex flex-col items-center text-center">
            {user.image ? (
              <img 
                src={user.image} 
                alt={user.name} 
                className="w-24 h-24 rounded-full object-cover border-4 border-surface-2 shadow-md mb-4 hover:scale-105 transition-transform duration-300"
              />
            ) : (
              <div className="w-24 h-24 rounded-full bg-gradient-to-br from-brand to-brand-hover flex items-center justify-center uppercase font-bold text-3xl text-white shadow-md mb-4 hover:scale-105 transition-transform duration-300 border-4 border-surface-2">
                {user.name?.charAt(0) ?? '?'}
              </div>
            )}
            
            <h1 className="text-xl font-bold text-foreground mb-1">{user.name}</h1>
            <p className="text-sm text-muted-foreground font-medium">{user.email}</p>
          </div>

          {/* Revora Branding Card */}
          <div className="rounded-xl border-2 border-border bg-brand/5 p-6 overflow-hidden relative group">
            <div className="flex items-center gap-3 mb-3 relative z-10">
              <div className="w-10 h-10 rounded-lg bg-brand/20 flex items-center justify-center border border-brand/30 shadow-inner">
                <ShieldCheck size={20} className="text-brand" />
              </div>
              <div>
                <h2 className="font-bold text-foreground font-heading tracking-tight text-lg" style={{ fontFamily: 'var(--font-oxanium, inherit)' }}>Revora</h2>
                <div className="text-[10px] text-brand font-bold uppercase tracking-wider">AI Code Review</div>
              </div>
            </div>
            <p className="text-sm font-medium text-foreground/80 leading-relaxed relative z-10">
              Open-source, repository-aware AI code review platform. Empowering developers with automated, intelligent PR insights.
            </p>
            <div className="mt-4 pt-4 border-t border-brand/20 relative z-10 flex justify-between items-center">
              <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Open Source</span>
              <a href="https://revora-pr.vercel.app/" target="_blank" rel="noopener noreferrer" className="cursor-target text-xs font-bold text-brand hover:text-brand-hover transition-colors flex items-center gap-1 bg-brand/10 px-2 py-1 rounded-md">
                revora.dev <ExternalLink size={12} />
              </a>
            </div>
          </div>

        </div>

        {/* Right Column (AI Providers & Activity) */}
        <div className="md:col-span-2 space-y-6">
          
          {/* AI Configuration */}
          <div className="rounded-xl border-2 border-border bg-surface-1 p-6 shadow-xl">
            <h2 className="text-sm font-bold uppercase tracking-wider text-foreground mb-4 flex items-center gap-2 border-b border-border pb-3">
              <CheckCircle2 size={18} className="text-brand" />
              Connected AI Providers
            </h2>
            
            {loading ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {[1, 2].map(i => (
                  <div key={i} className="h-16 rounded-xl bg-surface-2 border border-border animate-pulse" />
                ))}
              </div>
            ) : providers.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {providers.map((provider) => (
                  <div 
                    key={provider.slug} 
                    className="flex items-center justify-between p-4 rounded-xl border-2 border-border bg-surface-2 hover:border-brand/50 transition-colors shadow-sm"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-background border border-border shadow-sm">
                        <ProviderIcon slug={provider.slug} size={20} />
                      </div>
                      <span className="text-sm font-bold text-foreground">{provider.display_name || provider.name}</span>
                    </div>
                    <span className="text-[10px] uppercase font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/20 border border-emerald-200 dark:border-emerald-500/30 px-2 py-1 rounded-full">
                      Active
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 px-4 rounded-xl border-2 border-dashed border-border bg-surface-2">
                <GlobeIcon size={32} className="mx-auto text-muted-foreground mb-3 opacity-60" />
                <p className="text-base font-bold text-foreground mb-1">No AI providers connected yet.</p>
                <p className="text-sm font-medium text-muted-foreground mb-4">Configure a provider to start AI-powered reviews.</p>
                <Link href="/settings/providers" className="cursor-target text-sm font-bold text-brand hover:text-brand-hover bg-brand/10 px-4 py-2 rounded-lg transition-colors inline-block">
                  Configure Providers &rarr;
                </Link>
              </div>
            )}
          </div>

          {/* Activity Statistics */}
          <div className="rounded-xl border-2 border-border bg-surface-1 p-6 shadow-xl">
            <h2 className="text-sm font-bold uppercase tracking-wider text-foreground mb-4 flex items-center gap-2 border-b border-border pb-3">
              <ActivityIcon size={18} className="text-indigo-500 dark:text-indigo-400" />
              Review Activity
            </h2>
            
            {loading ? (
              <div className="grid grid-cols-2 gap-5">
                {[1, 2].map(i => (
                  <div key={i} className="h-28 rounded-xl bg-surface-2 border border-border animate-pulse" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-5">
                
                <div className="p-5 rounded-xl border-2 border-border bg-surface-2 flex flex-col justify-between group hover:border-indigo-500/50 hover:bg-indigo-50 dark:hover:bg-indigo-500/10 transition-colors shadow-sm">
                  <div className="flex items-center gap-2 text-foreground mb-3">
                    <div className="p-1.5 rounded-md bg-indigo-100 dark:bg-indigo-500/20 text-indigo-600 dark:text-indigo-400">
                      <GitFork size={18} />
                    </div>
                    <span className="text-xs font-bold uppercase tracking-wider">Repositories</span>
                  </div>
                  <div className="text-4xl font-extrabold text-foreground">
                    {stats?.connected_repos ?? 0}
                  </div>
                </div>

                <div className="p-5 rounded-xl border-2 border-border bg-surface-2 flex flex-col justify-between group hover:border-emerald-500/50 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 transition-colors shadow-sm">
                  <div className="flex items-center gap-2 text-foreground mb-3">
                    <div className="p-1.5 rounded-md bg-emerald-100 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400">
                      <GitPullRequest size={18} />
                    </div>
                    <span className="text-xs font-bold uppercase tracking-wider">PRs Reviewed</span>
                  </div>
                  <div className="text-4xl font-extrabold text-foreground">
                    {stats?.total_prs_reviewed ?? 0}
                  </div>
                </div>

              </div>
            )}
            
            {!loading && stats?.total_prs_reviewed === 0 && (
              <div className="mt-5 text-center py-6 rounded-xl border-2 border-dashed border-border bg-surface-2">
                <FileCode2 size={24} className="mx-auto text-muted-foreground mb-2 opacity-60" />
                <p className="text-sm font-bold text-foreground">Create your first pull request review to see activity here.</p>
              </div>
            )}

          </div>

        </div>

      </div>
    </div>
  );
}

// Temporary fallback icons for ones missing in lucide import
function ActivityIcon(props: any) {
  return <svg xmlns="http://www.w3.org/2000/svg" width={props.size||24} height={props.size||24} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={props.className}><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>;
}

function GlobeIcon(props: any) {
  return <svg xmlns="http://www.w3.org/2000/svg" width={props.size||24} height={props.size||24} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={props.className}><circle cx="12" cy="12" r="10"/><line x1="2" x2="22" y1="12" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>;
}
