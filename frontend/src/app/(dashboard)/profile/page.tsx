'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { HomeIcon, ChevronRightIcon } from 'lucide-react';
import { useAuthStore } from '@/store/useAuthStore';
import { api, Provider } from '@/lib/api';
import { ErrorBanner } from '@/components/shared/error-banner';
import { ProfileCard } from './_components/ProfileCard';
import { ConnectedProviders } from './_components/ConnectedProviders';

export default function ProfilePage() {
  const { user, sessionChecked } = useAuthStore();

  const [activeProviders, setActiveProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  // Both requests must succeed to compute "providers with a configured key",
  // so a failed request is an explicit error state — never an empty list that
  // would read as "no providers connected".
  const fetchData = useCallback(async () => {
    if (!sessionChecked || !user) return;
    setLoading(true);
    setLoadError(false);
    try {
      const [allProviders, apiKeys] = await Promise.all([
        api.getProviders(),
        api.getApiKeys(),
      ]);
      // Active = provider has an API key configured (unchanged business logic).
      const activeSlugs = new Set(apiKeys.map((key) => key.provider));
      setActiveProviders(allProviders.filter((p) => activeSlugs.has(p.slug)));
    } catch {
      setActiveProviders([]);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [sessionChecked, user]);

  useEffect(() => {
    // Load only once the session restore has settled AND a user is present.
    // This page deliberately does NOT redirect on its own: the (dashboard)
    // layout's guard already waits for sessionChecked and routes unauthorized
    // sessions to /login and unreachable backends to /waking-up. Redirecting
    // here on the transient `user === null` that the auth store serves on the
    // first client render after a hard refresh is what bounced a refreshed
    // /profile through /login (which the edge then rewrote to /dashboard).
    if (!sessionChecked || !user) return;
    // Deferred one microtask so state updates land in a callback, not
    // synchronously in the effect body.
    void Promise.resolve().then(fetchData);
  }, [sessionChecked, user, fetchData]);

  if (!user) return null;

  return (
    <div className="w-full">
      {/* Top-right account/theme controls are intentionally omitted on this
          page — the sidebar already provides the theme toggle and account
          section, so the Profile page does not duplicate them. */}
      <div className="max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 pb-24 md:pb-8">
        {/* Breadcrumb */}
        <nav aria-label="Breadcrumb" className="mb-5 md:mb-6">
          <ol className="flex items-center gap-1.5 text-sm">
            <li>
              <Link
                href="/dashboard"
                className="flex items-center text-muted-foreground hover:text-foreground transition-colors rounded focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                aria-label="Back to dashboard"
              >
                <HomeIcon size={16} aria-hidden="true" />
              </Link>
            </li>
            <li aria-hidden="true" className="text-muted-foreground/50">
              <ChevronRightIcon size={14} />
            </li>
            <li aria-current="page" className="font-semibold text-foreground">
              Profile
            </li>
          </ol>
        </nav>

        {/* Top-to-bottom landscape layout: profile card, then providers.
            Both sections span the full main-content width so their
            left/right edges align. */}
        <div className="space-y-5 md:space-y-6">
          <ProfileCard user={user} />
          {loadError ? (
            <ErrorBanner
              message="Couldn't load your connected providers. Your profile data is unaffected."
              action={
                <button
                  type="button"
                  onClick={() => void fetchData()}
                  className="cursor-pointer rounded-lg border border-error/30 px-3 py-1.5 text-xs font-medium text-error transition-colors hover:bg-error/10"
                >
                  Retry
                </button>
              }
            />
          ) : (
            <ConnectedProviders providers={activeProviders} loading={loading} />
          )}
        </div>
      </div>
    </div>
  );
}
