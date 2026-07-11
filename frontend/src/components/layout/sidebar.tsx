'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import { useRouter } from 'next/navigation';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { LayoutGridIcon, FolderIcon, ClipboardIcon, KeyIcon, LogoutIcon, MenuIcon, XIcon } from '@animateicons/react/lucide';
import { ThemeToggle } from '@/components/ui/theme-toggle';
import { useRef, useState, useEffect } from 'react';

const navLinks = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutGridIcon },
  { href: '/repositories', label: 'Repositories', icon: FolderIcon },
  { href: '/reviews', label: 'Reviews', icon: ClipboardIcon },
];

const bottomLinks = [
  { href: '/settings/api-keys', label: 'API Keys', icon: KeyIcon },
];

function NavLinkItem({ href, label, icon: Icon, isActive, collapsed }: { href: string; label: string; icon: any; isActive: boolean; collapsed: boolean }) {
  const iconRef = useRef<any>(null);
  return (
    <Link
      href={href}
      onMouseEnter={() => iconRef.current?.startAnimation()}
      onMouseLeave={() => iconRef.current?.stopAnimation()}
      title={collapsed ? label : undefined}
      className={`flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-150 ${
        collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5'
      } ${
        isActive
          ? 'bg-brand/15 text-brand-foreground shadow-[inset_0_0_0_1px_rgba(99,102,241,0.2)]'
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
      className={`flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-150 ${
        collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5'
      } ${
        isActive
          ? 'bg-brand/15 text-brand-foreground shadow-[inset_0_0_0_1px_rgba(99,102,241,0.2)]'
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

  // Auto-collapse on smaller screens
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)');
    const handler = (e: MediaQueryListEvent | MediaQueryList) => {
      if (e.matches) setCollapsed(true);
    };
    handler(mq);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const handleLogout = () => {
    logout();
    router.push('/login');
  };

  const isActive = (href: string) => pathname === href;

  const sidebarWidth = collapsed ? 'w-[68px]' : 'w-64';

  return (
    <>
      {/* Mobile hamburger button */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed top-4 left-4 z-50 md:hidden p-2 rounded-lg bg-surface-2 text-muted-foreground hover:text-foreground transition-colors"
        aria-label="Open menu"
      >
        <MenuIcon size={20} />
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed md:sticky top-0 h-screen ${sidebarWidth} border-r border-sidebar-border bg-sidebar flex flex-col shrink-0 transition-all duration-200 z-40 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        }`}
      >
        {/* Logo & collapse toggle */}
        <div className={`p-4 border-b border-sidebar-border flex items-center ${collapsed ? 'justify-center' : 'justify-between'}`}>
          {!collapsed && (
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 via-brand to-purple-600 flex items-center justify-center shadow-[0_0_16px_rgba(99,102,241,0.3)] shrink-0 overflow-hidden">
                <span className="flex items-center justify-center w-4 h-4">
                  <LoaderIcon size={16} className="text-white" />
                </span>
              </div>
              <div className="min-w-0">
                <span className="font-bold text-lg tracking-tight text-foreground block leading-tight">Revora</span>
                <div className="text-[10px] text-brand font-medium flex items-center gap-1 leading-tight">
                  <LoaderIcon size={8} className="text-brand" />
                  AI Code Review
                </div>
              </div>
            </div>
          )}
          <div className="flex items-center gap-1">
            {/* Theme toggle */}
            <ThemeToggle />
            {/* Mobile close button */}
            <button
              onClick={() => setMobileOpen(false)}
              className="md:hidden p-1 rounded text-muted-foreground hover:text-foreground"
              aria-label="Close menu"
            >
              <XIcon size={16} />
            </button>
            {/* Desktop collapse toggle */}
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="hidden md:flex p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors"
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <MenuIcon size={14} />
            </button>
          </div>
        </div>

        {/* Nav */}
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

        {/* User footer */}
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
            onClick={handleLogout}
            onMouseEnter={() => logoutIconRef.current?.startAnimation()}
            onMouseLeave={() => logoutIconRef.current?.stopAnimation()}
            title={collapsed ? 'Sign out' : undefined}
            className={`w-full flex items-center gap-2 rounded-lg text-sm text-muted-foreground hover:text-error hover:bg-error/10 transition-all duration-150 cursor-pointer ${
              collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5'
            }`}
          >
            <LogoutIcon ref={logoutIconRef} size={16} isAnimated={false} />
            {!collapsed && <span>Sign out</span>}
          </button>
        </div>
      </aside>
    </>
  );
}
