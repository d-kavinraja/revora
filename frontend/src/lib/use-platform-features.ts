'use client';

import { useQuery } from '@tanstack/react-query';
import { api, type PlatformFeatures } from '@/lib/api';

export const PLATFORM_FEATURES_KEY = ['platform-features'] as const;

/**
 * Public feature-flag map (§11.1). Fetched once per mount window and cached
 * (React Query dedupes across sidebar + pages). Fail-open: while loading or
 * on error, flags are treated as `enabled` — the server 503 is the real
 * enforcement, this only shapes the UI.
 */
export function usePlatformFeatures() {
  return useQuery({
    queryKey: PLATFORM_FEATURES_KEY,
    queryFn: api.getPlatformFeatures,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  });
}

export function featureState(
  features: PlatformFeatures | undefined,
  key: string
): { status: string; message: string | null } {
  const state = features?.[key];
  return {
    status: state?.status ?? 'enabled',
    message: state?.message ?? null,
  };
}

export function isFeatureEnabled(
  features: PlatformFeatures | undefined,
  key: string
): boolean {
  return featureState(features, key).status === 'enabled';
}
