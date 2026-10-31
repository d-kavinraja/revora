'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Image from 'next/image';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Boxes,
  FileText,
  Flag,
  FolderGit2,
  GitPullRequest,
  LayoutDashboard,
  Megaphone,
  Menu,
  Server,
  Users,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react';
import { adminApi } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { ThemeToggle } from '@/components/ui/theme-toggle';
import { useAdminThemeStore } from '@/store/useAdminThemeStore';

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  exact: boolean;
}

const NAV_GROUPS: ReadonlyArray<{ label: string; items: ReadonlyArray<NavItem> }> = [
  {
    label: 'Monitor',
    items: [
      { href: '/admin', label: 'Overview', icon: LayoutDashboard, exact: true },
      {
        href: '/admin/reviews',
        label: 'Reviews',
        icon: GitPullRequest,
        exact: false,
      },
      { href: '/admin/audit', label: 'Audit', icon: FileText, exact: false },
    ],
  },
  {
    label: 'Manage',
    items: [
      { href: '/admin/users', label: 'Users', icon: Users, exact: false },
      {
        href: '/admin/repositories',
        label: 'Repositories',
        icon: FolderGit2,
        exact: false,
      },
    ],
  },
  {
    label: 'System',
    items: [
      {
        href: '/admin/providers',
        label: 'Providers',
        icon: Server,
        exact: false,
      },
      { href: '/admin/models', label: 'Models', icon: Boxes, exact: false },
      { href: '/admin/features', label: 'Features', icon: Flag, exact: false },
      {
        href: '/admin/maintenance',
        label: 'Maintenance',
        icon: Wrench,
        exact: false,
      },
      {
        href: '/admin/announcements',
        label: 'Announcements',
        icon: Megaphone,
        exact: false,
      },
    ],
  },
];

const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

const SECTION_TITLES: Record<string, string> = {
  '/admin': 'Overview',
  '/admin/users': 'Users',
  '/admin/repositories': 'Repositories',
  '/admin/reviews': 'Reviews',
  '/admin/providers': 'Providers',
  '/admin/models': 'Models',
  '/admin/features': 'Features',
  '/admin/maintenance': 'Maintenance',
  '/admin/announcements': 'Announcements',
  '/admin/audit': 'Audit',
};

function isActive(pathname: string, href: string, exact: boolean): boolean {
  if (exact) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

function currentSection(pathname: string): string {
  const match = NAV_ITEMS.filter((item) =>
    isActive(pathname, item.href, item.exact),
  ).sort((a, b) => b.href.length - a.href.length)[0];
  return SECTION_TITLES[match?.href ?? ''] ?? 'Admin';
}

/**
 * Admin console shell. Self-guarding: proves the admin session against
 * `GET /admin/auth/session` on mount; 401 routes back to /admin/login.
 * The user-facing cookie/session is never consulted here.
 */
export default function AdminConsoleLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const adminTheme = useAdminThemeStore((s) => s.theme);
  const toggleAdminTheme = useAdminThemeStore((s) => s.toggleTheme);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const {
    data: session,
    isPending,
    isError,
  } = useQuery({
    queryKey: ['admin', 'session'],
    queryFn: adminApi.session,
    retry: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (isError) {
      router.replace('/admin/login');
    }
  }, [isError, router]);

  useEffect(() => {
    // The drawer is route-scoped UI: close it whenever the route changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDrawerOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const menuButton = menuButtonRef.current;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setDrawerOpen(false);
        return;
      }
      if (event.key !== 'Tab') return;
      const panel = drawerRef.current;
      if (!panel) return;
      const targets = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.offsetParent !== null);
      if (targets.length === 0) return;
      const first = targets[0];
      const last = targets[targets.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener('keydown', handleKey);
    return () => {
      window.removeEventListener('keydown', handleKey);
      document.body.style.overflow = previousOverflow;
      menuButton?.focus();
    };
  }, [drawerOpen]);

  const handleLogout = async () => {
    try {
      await adminApi.logout();
    } catch {
      // Even if the request fails, drop local state and return to login;
      // the cookie remains HttpOnly and expires server-side regardless.
    } finally {
      queryClient.removeQueries({ queryKey: ['admin'] });
      router.replace('/admin/login');
    }
  };

  if (isPending || isError || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <LoaderIcon size={24} className="text-brand" animate />
      </div>
    );
  }

  const section = currentSection(pathname);

  const renderNav = (onNavigate?: () => void) => (
    <nav aria-label="Admin sections" className="space-y-5 p-3">
      {NAV_GROUPS.map((group) => (
        <div key={group.label}>
          <p className="admin-eyebrow px-3 pb-1.5">{group.label}</p>
          <div className="space-y-1">
            {group.items.map((item) => {
              const active = isActive(pathname, item.href, item.exact);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? 'page' : undefined}
                  className={`group flex h-11 items-center gap-3 rounded-lg border px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                    active
                      ? 'border-brand/30 bg-brand/10 text-brand ring-1 ring-inset ring-brand/20'
                      : 'border-transparent text-foreground/70 hover:bg-[var(--admin-wash)] hover:text-foreground'
                  }`}
                >
                  <item.icon
                    size={17}
                    className={active ? 'text-brand' : 'text-muted-foreground group-hover:text-foreground'}
                  />
                  <span className="min-w-0 truncate">{item.label}</span>
                  {active && (
                    <span
                      aria-hidden="true"
                      className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
                    />
                  )}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );

  return (
    <div className="admin-motion min-h-screen bg-background">
      <header className="sticky top-0 z-30 border-b border-border bg-[var(--admin-topbar)] backdrop-blur-xl">
        <div className="flex h-16 items-center gap-3 px-4 md:px-6 lg:px-8">
          <button
            ref={menuButtonRef}
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
            aria-expanded={drawerOpen}
            className="inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-border text-foreground/70 transition-colors hover:bg-surface-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand lg:hidden"
          >
            <Menu size={18} />
          </button>

          <Link
            href="/admin"
            className="hidden w-60 shrink-0 items-center gap-3 rounded-lg pr-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand lg:flex"
          >
            <Image
              src="/revora-logo.png"
              alt="Revora"
              width={28}
              height={28}
              className="shrink-0 rounded-lg object-contain"
            />
            <span className="font-heading truncate text-sm font-semibold tracking-tight text-foreground">
              Revora
            </span>
            <span className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Admin
            </span>
          </Link>

          <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <Image
                src="/revora-logo.png"
                alt="Revora"
                width={26}
                height={26}
                className="shrink-0 rounded-lg object-contain lg:hidden"
              />
              <div className="min-w-0">
                <p className="admin-eyebrow hidden sm:block">Admin console</p>
                <p className="truncate text-sm font-semibold text-foreground">
                  {section}
                </p>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <span
                className="hidden max-w-[180px] truncate text-xs text-muted-foreground sm:block"
                title={session.username}
              >
                {session.username}
              </span>
              <span aria-hidden="true" className="hidden h-4 w-px bg-border sm:block" />
              <ThemeToggle
                theme={adminTheme}
                onToggle={toggleAdminTheme}
                className="h-9 w-9"
              />
              <button
                type="button"
                onClick={handleLogout}
                className="h-9 cursor-pointer rounded-lg border border-border px-3 text-sm font-medium text-foreground/80 transition-colors hover:bg-surface-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className="flex">
        <aside className="hidden w-60 shrink-0 border-r border-border bg-[var(--admin-rail)] lg:block">
          <div className="sticky top-16 max-h-[calc(100dvh-4rem)] overflow-y-auto">
            {renderNav()}
          </div>
        </aside>

        <main className="min-w-0 flex-1 p-4 md:p-6 lg:p-8">{children}</main>
      </div>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Admin navigation"
            tabIndex={-1}
            className="absolute inset-y-0 left-0 flex w-[280px] max-w-[85vw] flex-col border-r border-border bg-[var(--admin-rail)] shadow-2xl focus:outline-none"
          >
            <div className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-border px-4">
              <span className="flex min-w-0 items-center gap-3">
                <Image
                  src="/revora-logo.png"
                  alt="Revora"
                  width={26}
                  height={26}
                  className="shrink-0 rounded-lg object-contain"
                />
                <span className="font-heading truncate text-sm font-semibold tracking-tight text-foreground">
                  Revora Admin
                </span>
              </span>
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close navigation"
                className="inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                <X size={18} />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {renderNav(() => setDrawerOpen(false))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
