'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ThemeProvider } from '@/components/layout/theme-provider';
import { ToasterProvider } from '@/components/ui/toaster';
import { ServerStatusOverlay } from '@/components/ui/ServerStatusOverlay';
import { RuntimeErrorReporter } from '@/components/shared/runtime-error-reporter';
import { restoreSession } from '@/lib/api';

export function Providers({ children }: { children: React.ReactNode }) {
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

  // Re-establish the session from the HttpOnly cookie on first load of the
  // app shell (the JWT itself is never readable by page JavaScript).
  useEffect(() => {
    void restoreSession().catch((error) => {
      console.error('[auth] session restore failed unexpectedly', error);
    });
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
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
