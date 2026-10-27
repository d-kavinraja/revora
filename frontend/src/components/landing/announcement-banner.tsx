'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { api, type PublicAnnouncementRead } from '@/lib/api';

const DISMISSED_KEY = 'revora.dismissed-announcements';

function readDismissed(): Set<string> {
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? new Set(parsed.map(String)) : new Set();
  } catch {
    return new Set();
  }
}

function writeDismissed(ids: string[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(ids));
  } catch {
    /* noop */
  }
}

// Kind styling handled inline below; PROMINENT_KINDS retained for documentation.

function kindTone(kind: string): string {
  if (kind === 'service_interruption' || kind === 'scheduled_maintenance') {
    return 'border-error/40 bg-error/10 text-error';
  }
  if (kind === 'upgrade') {
    return 'border-brand/40 bg-brand/10 text-brand';
  }
  return 'border-border bg-surface-1 text-foreground/80';
}

export function AnnouncementBanner() {
  const { data: announcements } = useQuery({
    queryKey: ['platform-announcements'],
    queryFn: api.getAnnouncements,
    staleTime: 60_000,
    retry: false,
  });

  const dismissed = useMemo(() => readDismissed(), []);

  const visible = useMemo(() => {
    if (!announcements || announcements.length === 0) return [];
    return announcements.filter((a: PublicAnnouncementRead) => !dismissed.has(a.id));
  }, [announcements, dismissed]);

  if (visible.length === 0) return null;

  return (
    <div className="mx-auto max-w-5xl px-4 pt-4 space-y-2">
      {visible.map((a: PublicAnnouncementRead) => (
        <div
          key={a.id}
          role="status"
          aria-live="polite"
          className={`flex items-start gap-3 rounded-xl border p-4 text-sm ${kindTone(a.kind)}`}
        >
          <div className="min-w-0 flex-1">
            <p className="font-semibold">{a.title}</p>
            <p className="mt-0.5">{a.message}</p>
            {a.link_url && (
              <Link
                href={a.link_url}
                className="mt-1 inline-block underline underline-offset-2"
                target={a.link_url.startsWith('http') ? '_blank' : undefined}
                rel={a.link_url.startsWith('http') ? 'noopener noreferrer' : undefined}
              >
                {a.link_label || 'Learn more'}
              </Link>
            )}
          </div>
          {a.is_dismissible && (
            <button
              type="button"
              aria-label="Dismiss announcement"
              className="shrink-0 rounded-md p-1 hover:bg-black/5"
              onClick={() => {
                const next = Array.from(new Set([...readDismissed(), a.id]));
                writeDismissed(next);
                // Force re-render by reloading dismissed from storage.
                window.location.reload();
              }}
            >
              ×
            </button>
          )}
        </div>
      ))}
    </div>
  );
}