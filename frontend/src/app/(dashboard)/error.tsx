'use client';

import { useEffect } from 'react';
import { TriangleAlertIcon } from '@animateicons/react/lucide';

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="w-full h-full flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-surface-1 border border-border rounded-xl shadow-lg p-8 text-center space-y-5">
        <div className="w-12 h-12 bg-error/10 text-error rounded-full flex items-center justify-center mx-auto mb-2">
          <TriangleAlertIcon size={24} />
        </div>
        <h2 className="text-xl font-bold text-foreground">Something went wrong!</h2>
        <p className="text-muted-foreground text-sm">
          {error.message || 'An unexpected error occurred while loading this page.'}
        </p>
        <button
          onClick={() => reset()}
          className="px-5 py-2.5 bg-brand hover:bg-brand-hover text-brand-foreground rounded-lg text-sm font-semibold transition-colors mt-4 w-full"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
