'use client';

import Link from 'next/link';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import { useRouter } from 'next/navigation';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { LayoutGridIcon, FolderIcon, ClipboardIcon, KeyIcon, GlobeIcon, ChartBarIcon, ActivityIcon, GitBranchIcon, LogoutIcon, MenuIcon, XIcon, TrendingUpIcon } from '@animateicons/react/lucide';
import { ThemeToggle } from '@/components/ui/theme-toggle';
import { useRef, useState, useEffect } from 'react';

const navLinks = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutGridIcon },
  { href: '/repositories', label: 'Repositories', icon: FolderIcon },
  { href: '/reviews', label: 'Reviews', icon: ClipboardIcon },
];

const bottomLinks = [
  { href: '/settings/api-keys', label: 'API Keys', icon: KeyIcon },
  { href: '/settings/providers', label: 'Providers', icon: GlobeIcon },
  { href: '/settings/routing', label: 'Routing', icon: GitBranchIcon },
  { href: '/settings/usage', label: 'Usage', icon: ChartBarIcon },
  { href: '/settings/health', label: 'Health', icon: ActivityIcon },
  { href: '/settings/analytics', label: 'Analytics', icon: TrendingUpIcon },
];

function NavLinkItem({ href, label, icon: Icon, isActive, collapsed }: { href: string; label: string; icon: any; isActive: boolean; collapsed: boolean }) {
  const iconRef = useRef<any>(null);
  return (
    <Link
      href={href}
      onMouseEnter={() => iconRef.current?.startAnimation()}
      onMouseLeave={() => iconRef.current?.stopAnimation()}
      title={collapsed ? label : undefined}
      className={`cursor-target flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-150 ${
        collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5'
      } ${
        isActive
          ? 'bg-brand/15 text-brand shadow-[inset_0_0_0_1px_rgba(99,102,241,0.2)]'
          : 'text-muted-foreground hover:text-foreground hover:bg-white/[0.04]'
      }`}
    >
      <span className={isActive ? 'text-brand' : 'text-muted-foreground'}>
        <Icon ref={iconRef} size={16} isAnimated={false} />
      </span>
      {!collapsed && <span className="truncate">{label}</span>}
      {isActive && !collapsed && (
        <div className="ml-auto w-1.5 h-1.5 rounded-full bg-brand" />
      )}
    </Link>
  );
}

function BottomLinkItem({ href, label, icon: Icon, isActive, collapsed }: { href: string; label: string; icon: any; isActive: boolean; collapsed: boolean }) {
  const iconRef = useRef<any>(null);
  return (
    <Link
      href={href}
      onMouseEnter={() => iconRef.current?.startAnimation()}
      onMouseLeave={() => iconRef.current?.stopAnimation()}
      title={collapsed ? label : undefined}
      className={`cursor-target flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-150 ${
        collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5'
      } ${
        isActive
          ? 'bg-brand/15 text-brand shadow-[inset_0_0_0_1px_rgba(99,102,241,0.2)]'
          : 'text-muted-foreground hover:text-foreground hover:bg-white/[0.04]'
      }`}
    >
      <span className={isActive ? 'text-brand' : 'text-muted-foreground'}>
        <Icon ref={iconRef} size={16} isAnimated={false} />
      </span>
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  const router = useRouter();
  const logoutIconRef = useRef<any>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isLogoutModalOpen, setIsLogoutModalOpen] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)');
    const handler = (e: MediaQueryListEvent | MediaQueryList) => {
      if (e.matches) setCollapsed(true);
    };
    handler(mq);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const handleLogoutClick = () => {
    setIsLogoutModalOpen(true);
  };

  const handleConfirmLogout = () => {
    setIsLogoutModalOpen(false);
    logout();
    router.push('/login');
  };

  const isActive = (href: string) => pathname === href;

  const sidebarWidth = collapsed ? 'w-[68px]' : 'w-[240px]';

  return (
    <>
      <div className="md:hidden fixed top-0 left-0 right-0 h-16 bg-surface-1/80 backdrop-blur-md border-b border-border z-40 flex items-center px-4 justify-between shadow-sm">
        <div className="flex items-center gap-3">
          <Image src="/revora-logo.png" alt="Revora Logo" width={28} height={28} className="rounded-lg shadow-[0_0_12px_rgba(99,102,241,0.3)]" />
          <span className="font-bold text-base text-foreground font-heading" style={{ fontFamily: 'var(--font-oxanium, inherit)' }}>Revora</span>
        </div>
        <button
          onClick={() => setMobileOpen(true)}
          className="p-2 rounded-lg bg-surface-2 border border-border text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Open menu"
        >
          <MenuIcon size={20} />
        </button>
      </div>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={`fixed md:sticky top-0 h-screen ${sidebarWidth} border-r border-white/20 dark:border-white/10 bg-white/40 dark:bg-black/20 backdrop-blur-md flex flex-col shrink-0 transition-all duration-200 z-40 shadow-[4px_0_24px_rgba(0,0,0,0.02)] dark:shadow-[4px_0_24px_rgba(0,0,0,0.2)] ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        }`}
      >
        <div className={`p-4 border-b border-sidebar-border flex items-center ${collapsed ? 'justify-center' : 'justify-between'}`}>
          {!collapsed && (
            <div className="flex items-center gap-3 min-w-0">
              <Image
                src="/revora-logo.png"
                alt="Revora Logo"
                width={32}
                height={32}
                className="rounded-lg object-contain shrink-0 shadow-[0_0_16px_rgba(99,102,241,0.3)]"
              />
              <div className="min-w-0">
                <span className="font-bold text-lg tracking-tight text-foreground block leading-tight font-heading" style={{ fontFamily: 'var(--font-oxanium, inherit)' }}>Revora</span>
                <div className="text-[10px] text-brand font-medium flex items-center gap-1 leading-tight">
                  <LoaderIcon size={8} className="text-brand" />
                  AI Code Review
                </div>
              </div>
            </div>
          )}
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <button
              onClick={() => setMobileOpen(false)}
              className="md:hidden p-1 rounded text-muted-foreground hover:text-foreground"
              aria-label="Close menu"
            >
              <XIcon size={16} />
            </button>
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="hidden md:flex p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors"
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <MenuIcon size={14} />
            </button>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {!collapsed && (
            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-3 mb-2">
              Navigation
            </div>
          )}
          {navLinks.map((link) => (
            <NavLinkItem
              key={link.href}
              href={link.href}
              label={link.label}
              icon={link.icon}
              isActive={isActive(link.href)}
              collapsed={collapsed}
            />
          ))}

          {!collapsed && (
            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-3 mt-5 mb-2">
              Settings
            </div>
          )}
          {collapsed && <div className="my-3 mx-2 border-t border-sidebar-border" />}
          {bottomLinks.map((link) => (
            <BottomLinkItem
              key={link.href}
              href={link.href}
              label={link.label}
              icon={link.icon}
              isActive={isActive(link.href)}
              collapsed={collapsed}
            />
          ))}
        </nav>

        <div className="p-3 border-t border-sidebar-border">
          <div className={`flex items-center gap-3 px-2 mb-2 ${collapsed ? 'justify-center' : ''}`}>
            {user?.image ? (
              <img
                src={user.image}
                alt={user.name ?? 'User'}
                className="w-8 h-8 rounded-full object-cover shrink-0"
              />
            ) : (
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-brand to-purple-600 flex items-center justify-center uppercase font-bold text-xs text-white shrink-0">
                {user?.name?.charAt(0) ?? '?'}
              </div>
            )}
            {!collapsed && (
              <div className="min-w-0">
                <div className="text-sm font-semibold text-foreground truncate">{user?.name}</div>
                <div className="text-xs text-muted-foreground truncate">{user?.email}</div>
              </div>
            )}
          </div>
          <button
            onClick={handleLogoutClick}
            onMouseEnter={() => logoutIconRef.current?.startAnimation()}
            onMouseLeave={() => logoutIconRef.current?.stopAnimation()}
            className={`cursor-target w-full flex items-center gap-2 rounded-lg text-sm text-muted-foreground hover:text-error hover:bg-error/10 transition-all duration-150 cursor-pointer ${
              collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5'
            }`}
          >
            <LogoutIcon ref={logoutIconRef} size={16} isAnimated={false} />
            {!collapsed && <span>Sign out</span>}
          </button>
        </div>
      </aside>

      {isLogoutModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="p-6 rounded-xl border border-border bg-surface-1 text-foreground shadow-2xl flex flex-col gap-4 max-w-sm w-full mx-4">
            <h3 className="text-lg font-bold">Sign out</h3>
            <p className="text-sm text-muted-foreground">Are you sure you want to sign out?</p>
            <div className="flex justify-end gap-3 mt-4">
              <button
                onClick={() => setIsLogoutModalOpen(false)}
                className="cursor-target px-4 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmLogout}
                className="cursor-target px-4 py-2 rounded-lg text-sm font-medium bg-error text-white hover:bg-error/90 transition-colors"
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


