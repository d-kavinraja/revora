'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { HomeIcon, ChevronRightIcon } from 'lucide-react';
import { useAuthStore } from '@/store/useAuthStore';
import { api, Provider, ApiKey } from '@/lib/api';
import { ProfileCard } from './_components/ProfileCard';
import { ConnectedProviders } from './_components/ConnectedProviders';

export default function ProfilePage() {
  const router = useRouter();
  const { user } = useAuthStore();

  const [activeProviders, setActiveProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) {
      router.push('/login');
      return;
    }

    const fetchData = async () => {
      setLoading(true);

      // Each call degrades gracefully (unchanged pattern).
      const [allProviders, apiKeys] = await Promise.all([
        api.getProviders().catch(() => [] as Provider[]),
        api.getApiKeys().catch(() => [] as ApiKey[]),
      ]);

      // Active = provider has an API key configured (unchanged business logic).
      const activeSlugs = new Set(apiKeys.map((key) => key.provider));
      setActiveProviders(allProviders.filter((p) => activeSlugs.has(p.slug)));

      setLoading(false);
    };

    fetchData();
  }, [user, router]);

  if (!user) return null;

  return (
    <div className="w-full">
      {/* Top-right account/theme controls are intentionally omitted on this
          page — the sidebar already provides the theme toggle and account
          section, so the Profile page does not duplicate them. */}
      <div className="max-w-[1400px] mx-auto p-4 md:p-6 lg:p-8 pb-24 md:pb-8">
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
          <ConnectedProviders providers={activeProviders} loading={loading} />
        </div>
      </div>
    </div>
  );
}
