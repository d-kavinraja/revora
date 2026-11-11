'use client';

import { useEffect } from 'react';

type ErrorLike = {
  name?: string;
  message?: string;
  stack?: string;
  filename?: string;
  lineno?: number;
  colno?: number;
};

function describeReason(reason: unknown): Record<string, unknown> {
  if (reason instanceof ErrorEvent) {
    return {
      kind: 'ErrorEvent',
      message: reason.message,
      filename: reason.filename,
      lineno: reason.lineno,
      colno: reason.colno,
      error: reason.error ? describeReason(reason.error) : null,
    };
  }
  if (reason instanceof Error) {
    const value = reason as Error & ErrorLike;
    return {
      kind: reason.name || 'Error',
      message: reason.message,
      stack: reason.stack,
      cause: 'cause' in reason ? describeReason(reason.cause) : undefined,
      filename: value.filename,
      lineno: value.lineno,
      colno: value.colno,
    };
  }
  if (reason instanceof Event) {
    const target = reason.target as { src?: string; href?: string } | null;
    return {
      kind: `Event:${reason.type}`,
      targetSrc: target?.src ?? target?.href ?? null,
    };
  }
  if (typeof reason === 'string') return { kind: 'string', message: reason };
  try {
    return { kind: typeof reason, value: JSON.stringify(reason) };
  } catch {
    return { kind: typeof reason, value: String(reason) };
  }
}

/**
 * Browser-side diagnostics for the two events Next's dev overlay renders as
 * the opaque `[object ErrorEvent]`. The handler never suppresses or swallows
 * the error; it only records the real message, source and stack so the source
 * can be identified. Deduplicated because a broken stream can repeat rapidly.
 */
export function RuntimeErrorReporter() {
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const seen = new Set<string>();
    const logOnce = (channel: string, payload: Record<string, unknown>) => {
      let signature: string;
      try {
        signature = `${channel}:${JSON.stringify(payload)}`;
      } catch {
        signature = `${channel}:unknown`;
      }
      if (seen.has(signature)) return;
      seen.add(signature);
      if (seen.size > 50) seen.clear();
      console.error(`[runtime] ${channel}`, {
        ...payload,
        pathname: window.location.pathname,
        visibility: document.visibilityState,
        at: new Date().toISOString(),
      });
    };

    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      logOnce('unhandledrejection', {
        reason: describeReason(event.reason),
      });
    };

    const onWindowError = (event: ErrorEvent) => {
      // Resource load errors (script/img) have no message; still record the
      // target so they are not mistaken for application exceptions.
      const target = event.target as { src?: string; href?: string } | null;
      logOnce('window.error', {
        message: event.message,
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
        error: event.error ? describeReason(event.error) : null,
        targetSrc: target?.src ?? target?.href ?? null,
      });
    };

    window.addEventListener('unhandledrejection', onUnhandledRejection);
    window.addEventListener('error', onWindowError, true);
    return () => {
      window.removeEventListener('unhandledrejection', onUnhandledRejection);
      window.removeEventListener('error', onWindowError, true);
    };
  }, []);

  return null;
}
