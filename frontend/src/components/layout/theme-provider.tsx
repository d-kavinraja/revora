'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { useThemeStore } from '@/store/useThemeStore';
import { useAdminThemeStore } from '@/store/useAdminThemeStore';

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAdmin = pathname?.startsWith('/admin') ?? false;
  const theme = useThemeStore((s) => s.theme);
  const adminTheme = useAdminThemeStore((s) => s.theme);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove('light', 'dark', 'admin-light', 'admin-dark');
    if (isAdmin) {
      root.classList.add(adminTheme === 'dark' ? 'admin-dark' : 'admin-light');
    } else {
      root.classList.add(theme);
    }
  }, [theme, adminTheme, isAdmin]);

  useEffect(() => {
    if (isAdmin) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => {
      const stored = localStorage.getItem('revora-theme');
      if (!stored) {
        useThemeStore.getState().setTheme(e.matches ? 'dark' : 'light');
      }
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [isAdmin]);

  return <>{children}</>;
}