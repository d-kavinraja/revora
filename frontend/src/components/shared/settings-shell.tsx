'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { usePlatformFeatures, isFeatureEnabled } from '@/lib/use-platform-features';

/**
 * Settings section navigation. The seven settings pages previously had no
 * in-page way to reach each other; this band is the shared wayfinding. Tabs
 * mirror the sidebar's Settings group order (connection first, observability
 * last) and its feature-flag treatment: always visible, styled down when the
 * feature is off.
 */
const SETTINGS_TABS: { href: string; label: string; feature?: string }[] = [
  { href: '/settings/api-keys', label: 'API keys' },
  { href: '/settings/providers', label: 'Providers' },
  { href: '/settings/kllm', label: 'kLLM', feature: 'kllm_page' },
  { href: '/settings/routing', label: 'Routing' },
  { href: '/settings/health', label: 'Health' },
  { href: '/settings/usage', label: 'Usage', feature: 'usage' },
  { href: '/settings/analytics', label: 'Analytics', feature: 'analytics' },
];

export function SettingsShell() {
  const pathname = usePathname();
  const { data: features } = usePlatformFeatures();

  return (
    <nav
      aria-label="Settings sections"
      className="-mx-4 mb-8 overflow-x-auto border-b border-border px-4 md:mx-0 md:px-0"
    >
      <ul className="flex min-w-max items-center gap-1 pr-4 md:pr-0">
        {SETTINGS_TABS.map((tab) => {
          const active =
            pathname === tab.href || pathname.startsWith(tab.href + '/');
          const disabled = !!tab.feature && !isFeatureEnabled(features, tab.feature);
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={active ? 'page' : undefined}
                aria-disabled={disabled || undefined}
                onClick={(event) => {
                  if (disabled) event.preventDefault();
                }}
                className={`-mb-px flex h-10 items-center border-b-2 px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                  active
                    ? 'border-brand text-brand'
                    : disabled
                      ? 'cursor-not-allowed border-transparent text-muted-foreground/50'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}