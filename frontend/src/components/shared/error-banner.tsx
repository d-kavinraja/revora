'use client';

import { type ReactNode } from 'react';
import { TriangleAlertIcon } from '@animateicons/react/lucide';

/**
 * One page-level error pattern: what happened, and the way forward.
 * Used for load failures; action results keep using toasts.
 */
export function ErrorBanner({
  message,
  action,
}: {
  message: string;
  action?: ReactNode;
}) {
  return (
    <div
      role="alert"
      className="mb-6 flex flex-wrap items-center gap-3 rounded-lg border border-error/30 bg-error/10 p-4"
    >
      <TriangleAlertIcon size={20} className="shrink-0 text-error" />
      <p className="min-w-0 flex-1 text-sm text-error">{message}</p>
      {action}
    </div>
  );
}