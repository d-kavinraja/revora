'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { ThemeProvider } from '@/components/layout/theme-provider';
import { ToasterProvider } from '@/components/ui/toaster';

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

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToasterProvider>
          {children}
        </ToasterProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
