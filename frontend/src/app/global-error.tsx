'use client';

import { TriangleAlertIcon } from '@animateicons/react/lucide';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background text-foreground antialiased font-sans flex items-center justify-center p-6">
        <div className="max-w-md w-full bg-surface-1 border border-border rounded-xl shadow-lg p-8 text-center space-y-5">
          <div className="w-12 h-12 bg-error/10 text-error rounded-full flex items-center justify-center mx-auto mb-2">
            <TriangleAlertIcon size={24} />
          </div>
          <h2 className="text-xl font-bold text-foreground">A critical error occurred!</h2>
          <p className="text-muted-foreground text-sm">
            {error.message || 'An unexpected error occurred while loading this page.'}
          </p>
          <button
            onClick={() => reset()}
            className="px-5 py-2.5 bg-brand hover:bg-brand-hover text-brand-foreground rounded-lg text-sm font-semibold transition-colors mt-4 w-full cursor-pointer"
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
