'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import { useRouter } from 'next/navigation';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { LayoutGridIcon, FolderIcon, ClipboardIcon, KeyIcon, LogoutIcon } from '@animateicons/react/lucide';
import { useRef } from 'react';

const navLinks = [
  {
    href: '/dashboard',
    label: 'Dashboard',
    icon: LayoutGridIcon,
  },
  {
    href: '/repositories',
    label: 'Repositories',
    icon: FolderIcon,
  },
  {
    href: '/reviews',
    label: 'Reviews',
    icon: ClipboardIcon,
  },
];

const bottomLinks = [
  {
    href: '/settings/api-keys',
    label: 'API Keys',
    icon: KeyIcon,
  },
];

function NavLinkItem({ href, label, icon: Icon, isActive }: { href: string; label: string; icon: any; isActive: boolean }) {
  const iconRef = useRef<any>(null);
  return (
    <Link
      href={href}
      onMouseEnter={() => iconRef.current?.startAnimation()}
      onMouseLeave={() => iconRef.current?.stopAnimation()}
      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
        isActive
          ? 'bg-indigo-500/15 text-indigo-300 shadow-[inset_0_0_0_1px_rgba(99,102,241,0.25)]'
          : 'text-zinc-400 hover:text-white hover:bg-white/5'
      }`}
    >
      <span className={isActive ? 'text-indigo-400' : 'text-zinc-500'}>
        <Icon ref={iconRef} size={16} isAnimated={false} />
      </span>
      {label}
      {isActive && (
        <div className="ml-auto w-1.5 h-1.5 rounded-full bg-indigo-400"></div>
      )}
    </Link>
  );
}

function BottomLinkItem({ href, label, icon: Icon, isActive }: { href: string; label: string; icon: any; isActive: boolean }) {
  const iconRef = useRef<any>(null);
  return (
    <Link
      href={href}
      onMouseEnter={() => iconRef.current?.startAnimation()}
      onMouseLeave={() => iconRef.current?.stopAnimation()}
      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
        isActive
          ? 'bg-indigo-500/15 text-indigo-300 shadow-[inset_0_0_0_1px_rgba(99,102,241,0.25)]'
          : 'text-zinc-400 hover:text-white hover:bg-white/5'
      }`}
    >
      <span className={isActive ? 'text-indigo-400' : 'text-zinc-500'}>
        <Icon ref={iconRef} size={16} isAnimated={false} />
      </span>
      {label}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  const router = useRouter();
  const logoutIconRef = useRef<any>(null);

  const handleLogout = () => {
    logout();
    router.push('/login');
  };

  const isActive = (href: string) => pathname === href;

  return (
    <aside className="w-64 min-h-screen border-r border-white/5 bg-[#0a0a0f] flex flex-col shrink-0">
      {/* Logo */}
      <div className="p-6 border-b border-white/5">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 via-indigo-500 to-purple-600 flex items-center justify-center shadow-[0_0_20px_rgba(99,102,241,0.4)]">
            <LoaderIcon size={16} className="text-white" />
          </div>
          <div>
            <span className="font-bold text-lg tracking-tight text-white">Revora</span>
            <div className="text-[10px] text-indigo-400 font-medium -mt-0.5 flex items-center gap-1">
              <LoaderIcon size={10} className="text-indigo-400" />
              AI Code Review
            </div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-4 space-y-1">
        <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest px-3 mb-3">
          Navigation
        </div>
        {navLinks.map((link) => (
          <NavLinkItem
            key={link.href}
            href={link.href}
            label={link.label}
            icon={link.icon}
            isActive={isActive(link.href)}
          />
        ))}

        <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest px-3 mt-6 mb-3">
          Settings
        </div>
        {bottomLinks.map((link) => (
          <BottomLinkItem
            key={link.href}
            href={link.href}
            label={link.label}
            icon={link.icon}
            isActive={isActive(link.href)}
          />
        ))}
      </nav>

      {/* User footer */}
      <div className="p-4 border-t border-white/5">
        <div className="flex items-center gap-3 px-2 mb-3">
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center uppercase font-bold text-sm text-white shrink-0">
            {user?.name?.charAt(0) ?? '?'}
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-white truncate">{user?.name}</div>
            <div className="text-xs text-zinc-500 truncate">{user?.email}</div>
          </div>
        </div>
        <button
          onClick={handleLogout}
          onMouseEnter={() => logoutIconRef.current?.startAnimation()}
          onMouseLeave={() => logoutIconRef.current?.stopAnimation()}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-zinc-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all duration-200 cursor-pointer"
        >
          <LogoutIcon ref={logoutIconRef} size={16} isAnimated={false} />
          Sign out
        </button>
      </div>
    </aside>
  );
}
