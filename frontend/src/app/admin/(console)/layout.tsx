'use client';

import { useEffect } from 'react';
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
  Server,
  Users,
  Wrench,
} from 'lucide-react';
import { adminApi } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { ThemeToggle } from '@/components/ui/theme-toggle';
import { useAdminThemeStore } from '@/store/useAdminThemeStore';

const NAV_ITEMS = [
  { href: '/admin', label: 'Overview', icon: LayoutDashboard, exact: true },
  { href: '/admin/users', label: 'Users', icon: Users, exact: false },
  {
    href: '/admin/repositories',
    label: 'Repositories',
    icon: FolderGit2,
    exact: false,
  },
  {
    href: '/admin/reviews',
    label: 'Reviews',
    icon: GitPullRequest,
    exact: false,
  },
  {
    href: '/admin/providers',
    label: 'Providers',
    icon: Server,
    exact: false,
  },
  {
    href: '/admin/models',
    label: 'Models',
    icon: Boxes,
    exact: false,
  },
  {
    href: '/admin/features',
    label: 'Features',
    icon: Flag,
    exact: false,
  },
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
  {
    href: '/admin/audit',
    label: 'Audit',
    icon: FileText,
    exact: false,
  },
];

function isActive(pathname: string, href: string, exact: boolean): boolean {
  if (exact) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
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
      <div className="min-h-screen flex items-center justify-center bg-background">
        <LoaderIcon size={24} className="text-brand" animate />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 border-b border-border bg-surface-1/80 backdrop-blur-lg">
        {/* Left-anchored, full available width: the brand zone mirrors the
            `w-52` sidebar so the header, divider and content share edges, and
            the content column takes the whole viewport minus the sidebar
            (previously capped at 1200px, which starved wide data tables). */}
        <div className="w-full mr-auto flex h-14 items-center">
          <div className="hidden lg:flex w-52 shrink-0 items-center gap-3 px-4 min-w-0 border-r border-border h-full">
            <Image
              src="/revora-logo.png"
              alt="Revora"
              width={28}
              height={28}
              className="rounded-lg object-contain shrink-0"
            />
            <span className="font-semibold text-sm text-foreground truncate">
              Revora Admin
            </span>
          </div>
          <div className="flex-1 min-w-0 flex items-center justify-between gap-4 px-4 md:px-6 lg:px-8">
            <span className="lg:hidden flex items-center gap-3 min-w-0">
              <Image
                src="/revora-logo.png"
                alt="Revora"
                width={28}
                height={28}
                className="rounded-lg object-contain shrink-0"
              />
              <span className="font-semibold text-sm text-foreground truncate">
                Revora Admin
              </span>
              <span className="hidden sm:inline-block text-[11px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-brand/10 text-brand border border-brand/30">
                Console
              </span>
            </span>
            <span className="hidden lg:inline-block text-[11px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-brand/10 text-brand border border-brand/30">
              Console
            </span>
            <div className="flex items-center gap-3 shrink-0">
              <span className="hidden sm:block text-xs text-muted-foreground truncate max-w-[180px]">
                {session.username}
              </span>
              <ThemeToggle
                theme={adminTheme}
                onToggle={toggleAdminTheme}
                className="h-9 w-9"
              />
              <button
                type="button"
                onClick={handleLogout}
                className="h-9 px-3 rounded-lg border border-border text-sm font-medium text-foreground/80 hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1"
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className="w-full mr-auto flex">
        <aside className="hidden lg:block w-52 shrink-0 border-r border-border">
          <nav
            aria-label="Admin sections"
            className="sticky top-14 p-4 space-y-1"
          >
            {NAV_ITEMS.map((item) => {
              const active = isActive(pathname, item.href, item.exact);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? 'page' : undefined}
                  className={`flex items-center gap-3 h-11 px-3 rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                    active
                      ? 'bg-brand/10 text-brand border border-brand/30'
                      : 'text-foreground/75 hover:text-foreground hover:bg-surface-2 border border-transparent'
                  }`}
                >
                  <item.icon size={17} />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>

        <div className="flex-1 min-w-0">
          <nav
            aria-label="Admin sections"
            className="lg:hidden border-b border-border bg-surface-1/60 overflow-x-auto"
          >
            <div className="flex items-center gap-1.5 px-4 py-2">
              {NAV_ITEMS.map((item) => {
                const active = isActive(pathname, item.href, item.exact);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? 'page' : undefined}
                    className={`flex items-center gap-2 h-11 px-3 rounded-lg text-sm font-medium whitespace-nowrap transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                      active
                        ? 'bg-brand/10 text-brand border border-brand/30'
                        : 'text-foreground/75 hover:text-foreground hover:bg-surface-2 border border-transparent'
                    }`}
                  >
                    <item.icon size={16} />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </nav>

          <main className="p-4 md:p-6 lg:p-8 min-w-0">{children}</main>
        </div>
      </div>
    </div>
  );
}
