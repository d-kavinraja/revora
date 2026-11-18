'use client';

import { Info } from 'lucide-react';
import { usePathname } from 'next/navigation';

import { matchFeaturePage } from '@/lib/feature-pages';
import { usePlatformFeatures } from '@/lib/use-platform-features';
import { cn } from '@/lib/utils';

interface FeatureNotice {
  key: string;
  message: string;
}

/**
 * Persistent admin-configured notices for enabled features.
 *
 * This is intentionally display-only: it reads the public feature-flag map
 * and never changes status, access control or the server-side 503 gate.
 * Messages for non-enabled features stay on the existing unavailable screen.
 */
export function FeatureNoticeBanner({ className }: { className?: string }) {
  const pathname = usePathname();
  const { data: features } = usePlatformFeatures();
  const route = matchFeaturePage(pathname);

  if (!route) return null;

  // A disabled/maintenance/coming-soon/under-testing full page already shows
  // its configured message in FeatureUnavailable; never add a banner above it.
  if (
    route.gateFeature &&
    features?.[route.gateFeature]?.status !== 'enabled'
  ) {
    return null;
  }

  const notices: FeatureNotice[] = [];
  for (const key of route.features) {
    const state = features?.[key];
    if (state?.status !== 'enabled') continue;

    const message = state.message?.trim();
    if (message) notices.push({ key, message });
  }

  if (notices.length === 0) return null;

  return (
    <div
      className={cn(
        'mx-auto w-full max-w-[1200px] px-4 pt-4 md:px-6 md:pt-6 lg:px-8',
        className,
      )}
    >
      <div className="space-y-2">
        {notices.map(({ key, message }) => (
          <div
            key={key}
            role="status"
            className="flex items-start gap-3 rounded-xl border border-info/30 bg-info/10 p-4 text-sm leading-relaxed text-foreground shadow-sm shadow-black/5 md:p-5"
          >
            <Info
              className="mt-0.5 h-4 w-4 shrink-0 text-info md:h-[18px] md:w-[18px]"
              aria-hidden="true"
            />
            <p className="min-w-0 break-words">{message}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
