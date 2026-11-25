'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ThemeProvider } from '@/components/layout/theme-provider';
import { ToasterProvider } from '@/components/ui/toaster';
import { ServerStatusOverlay } from '@/components/ui/ServerStatusOverlay';
import { RuntimeErrorReporter } from '@/components/shared/runtime-error-reporter';
import { restoreSession } from '@/lib/api';
import { useThemeStore } from '@/store/useThemeStore';
import { useAdminThemeStore } from '@/store/useAdminThemeStore';
import { useAuthStore } from '@/store/useAuthStore';

export function Providers({ children }: { children: React.ReactNode }) {
  const [preferencesHydrated, setPreferencesHydrated] = useState(false);
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 1000,
            refetchOnWindowFocus: true,
            retry: 1,
          },
        },
      })
  );

  // Zustand's browser storage is rehydrated after the first client render so
  // SSR and hydration start from the same defaults. Session restoration runs
  // afterwards: the cookie-backed profile must never be overwritten by a stale
  // profile read from localStorage during rehydration.
  useEffect(() => {
    void Promise.allSettled([
      useThemeStore.persist.rehydrate(),
      useAdminThemeStore.persist.rehydrate(),
      useAuthStore.persist.rehydrate(),
    ]).then(() => {
      setPreferencesHydrated(true);
      return restoreSession();
    }).catch((error) => {
      console.error('[auth] session restore failed unexpectedly', error);
    });
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider preferencesHydrated={preferencesHydrated}>
        <ToasterProvider>
          <RuntimeErrorReporter />
          {/* Global server health monitor — shows blur overlay when backend goes down */}
          <ServerStatusOverlay />
          {children}
        </ToasterProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
