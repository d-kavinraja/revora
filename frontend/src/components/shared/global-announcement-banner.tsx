'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  ChevronLeft,
  ChevronRight,
  Megaphone,
  Rocket,
  TriangleAlert,
  Wrench,
  X,
} from 'lucide-react';
import { api, readDeviceId, type PublicAnnouncementRead } from '@/lib/api';
import { useAuthStore } from '@/store/useAuthStore';

export const PLATFORM_ANNOUNCEMENTS_KEY = 'platform-announcements';

function kindIcon(kind: string): { Icon: typeof Megaphone; className: string } {
  if (kind === 'service_interruption') {
    return { Icon: TriangleAlert, className: 'text-[var(--announcement-icon)]' };
  }
  if (kind === 'scheduled_maintenance') {
    return { Icon: Wrench, className: 'text-[var(--announcement-icon)]' };
  }
  if (kind === 'upgrade' || kind === 'new_feature') {
    return { Icon: Rocket, className: 'text-[var(--announcement-icon)]' };
  }
  return { Icon: Megaphone, className: 'text-[var(--announcement-icon)]' };
}

export function GlobalAnnouncementBanner() {
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const isAdmin = pathname?.startsWith('/admin') ?? false;
  const isAuthRoute =
    !!pathname &&
    (pathname.startsWith('/login') ||
      pathname.startsWith('/register') ||
      pathname.startsWith('/auth') ||
      pathname.startsWith('/waking-up'));

  // The feed is resolved server-side for the calling subject (signed-in
  // user, else anonymous device): dismissals are never a browser-local
  // list, and an updated announcement (new version) is eligible again.
  // The subject scope is part of the cache key so signing in or out
  // refetches the feed with the right subject.
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const deviceId = useMemo(() => readDeviceId(), []);
  const subjectKey = isAuthenticated
    ? `user:${user?.id ?? 'anonymous'}`
    : `device:${deviceId ?? 'anonymous'}`;

  const { data: announcements } = useQuery({
    queryKey: [PLATFORM_ANNOUNCEMENTS_KEY, subjectKey],
    queryFn: api.getAnnouncements,
    enabled: !isAdmin,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: false,
  });

  // Optimistic dismissals are keyed by id AND version: when an admin
  // updates the announcement the version changes, the new version becomes
  // eligible again and must reappear without a reload. The map is scoped
  // to the actual subject (signed-in user id or anonymous device id) so
  // switching accounts or browsers never shows another subject's dismissals.
  const [dismissedBySubject, setDismissedBySubject] = useState<
    Record<string, Record<string, number>>
  >({});
  const dismissed = useMemo(
    () => dismissedBySubject[subjectKey] ?? {},
    [dismissedBySubject, subjectKey],
  );

  const visible = useMemo(() => {
    if (!announcements || announcements.length === 0) return [];
    return announcements.filter(
      (a: PublicAnnouncementRead) => dismissed[a.id] !== a.version,
    );
  }, [announcements, dismissed]);

  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const reducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  useEffect(() => {
    if (visible.length <= 1 || paused || reducedMotion) return;
    const t = window.setInterval(() => {
      setIndex((i) => (i + 1) % visible.length);
    }, 8000);
    return () => window.clearInterval(t);
  }, [visible.length, paused, reducedMotion]);

  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = containerRef.current;
    if (!el || isAdmin || visible.length === 0) {
      document.documentElement.style.setProperty('--revora-announcement-height', '0px');
      return;
    }
    const update = () => {
      const h = el.getBoundingClientRect().height;
      document.documentElement.style.setProperty('--revora-announcement-height', `${h}px`);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => {
      ro.disconnect();
      document.documentElement.style.setProperty('--revora-announcement-height', '0px');
    };
  }, [isAdmin, visible.length]);

  const safeIndex = Math.min(index, Math.max(visible.length - 1, 0));
  const current = visible[safeIndex];

  // Mark the announcement as seen once it becomes the active one. Only
  // dismissible "every_login" announcements need this marker (it prevents
  // the same announcement from being displayed repeatedly inside one login
  // session); non-dismissible announcements stay visible, and the other
  // policies are unaffected by it.
  const seenRef = useRef<Map<string, Set<string>>>(new Map());
  useEffect(() => {
    if (
      !current ||
      current.display_policy !== 'every_login' ||
      !current.is_dismissible
    ) {
      return;
    }
    const key = `${current.id}:${current.version}`;
    const seenForSubject = seenRef.current.get(subjectKey) ?? new Set<string>();
    if (seenForSubject.has(key)) return;
    seenForSubject.add(key);
    seenRef.current.set(subjectKey, seenForSubject);
    void api.markAnnouncementSeen(current.id).catch(() => {
      /* best-effort: a failed marker must not break the banner */
    });
  }, [current, subjectKey]);

  if (isAdmin || visible.length === 0 || !current) return null;

  const { Icon, className: iconTone } = kindIcon(current.kind);

  const dismiss = () => {
    const id = current.id;
    const version = current.version;
    // Optimistic removal; the server persists the dismissal for this
    // subject so it stays hidden after refresh, logout and across devices.
    const markDismissed = (apply: (prev: Record<string, number>) => Record<string, number>) =>
      setDismissedBySubject((prev) => ({
        ...prev,
        [subjectKey]: apply(prev[subjectKey] ?? {}),
      }));

    markDismissed((prev) => ({ ...prev, [id]: version }));
    void api.dismissAnnouncement(id).catch(() => {
      // Roll back the optimistic removal if the server refused it.
      markDismissed((prev) => {
        if (prev[id] !== version) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      });
    });
    void queryClient.invalidateQueries({ queryKey: [PLATFORM_ANNOUNCEMENTS_KEY] });
  };
  const prev = () => setIndex((i) => (i - 1 + visible.length) % visible.length);
  const next = () => setIndex((i) => (i + 1) % visible.length);

  const controlCls = isAuthRoute
    ? 'text-white/80 hover:bg-white/10 hover:text-white'
    : 'text-[var(--announcement-control)] hover:bg-black/5 dark:hover:bg-white/5 hover:text-[var(--announcement-title)]';

  return (
    <div
      ref={containerRef}
      className={`fixed inset-x-0 top-0 z-[70] border-b ${
        isAuthRoute
          ? 'border-white/10 bg-[#090909] text-white'
          : 'border-[var(--announcement-border)] bg-[var(--announcement-bg)] text-[var(--announcement-title)]'
      }`}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <div className="grid w-full grid-cols-[minmax(2rem,auto)_1fr_minmax(2rem,auto)] items-center gap-x-3 px-4 py-2.5 sm:px-6 lg:px-8">
        <div aria-hidden="true" />

        <div
          role="status"
          aria-live="polite"
          className="flex min-w-0 flex-wrap items-center justify-center gap-x-2 gap-y-1"
        >
          <Icon
            size={16}
            aria-hidden="true"
            className={`mt-0.5 shrink-0 sm:mt-0 ${isAuthRoute ? 'text-white' : iconTone}`}
          />

          <p
            className={`shrink-0 text-sm font-semibold leading-snug ${
              isAuthRoute ? 'text-white' : 'text-[var(--announcement-title)]'
            }`}
          >
            {current.title}
          </p>
          <p
            className={`min-w-0 text-sm leading-snug break-words ${
              isAuthRoute ? 'text-[#E5E5E5]' : 'text-[var(--announcement-text)]'
            }`}
          >
            {current.message}
            {current.link_url && (
              <>
                {' '}
                <Link
                  href={current.link_url}
                  className="underline underline-offset-2 hover:opacity-80"
                  target={current.link_url.startsWith('http') ? '_blank' : undefined}
                  rel={current.link_url.startsWith('http') ? 'noopener noreferrer' : undefined}
                >
                  {current.link_label || 'Learn more'}
                </Link>
              </>
            )}
          </p>

          {visible.length > 1 && (
            <div className={`flex shrink-0 items-center gap-0.5 text-xs ${controlCls}`}>
              <button
                type="button"
                aria-label="Previous announcement"
                onClick={prev}
                className="rounded-md p-1"
              >
                <ChevronLeft size={14} />
              </button>
              <span className="tabular-nums whitespace-nowrap">
                {safeIndex + 1} of {visible.length}
              </span>
              <button
                type="button"
                aria-label="Next announcement"
                onClick={next}
                className="rounded-md p-1"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          )}
        </div>

        <div className="flex justify-end">
          {current.is_dismissible && (
            <button
              type="button"
              aria-label="Dismiss announcement"
              className={`shrink-0 rounded-md p-1.5 ${controlCls}`}
              onClick={dismiss}
            >
              <X size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
