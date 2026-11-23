'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { useThemeStore } from '@/store/useThemeStore';
import { useAdminThemeStore } from '@/store/useAdminThemeStore';

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAdmin = pathname?.startsWith('/admin') ?? false;
  const theme = useThemeStore((s) => s.theme);
  const adminTheme = useAdminThemeStore((s) => s.theme);

  const prevPathnameRef = useRef<string | null>(null);
  const savedPreChatThemeRef = useRef<'dark' | 'light' | null>(null);
  const chatThemeRef = useRef<'light' | 'dark' | null>(null);

  // Manual toggle detector while on /chat. Subscribes to theme changes so we
  // can distinguish a user-initiated toggle from the auto-switch on entry.
  // Unsubscribes when leaving /chat.
  useEffect(() => {
    if (pathname !== '/chat') return;
    const unsubscribe = useThemeStore.subscribe((state, prev) => {
      if (state.theme === prev.theme) return;
      if (chatThemeRef.current === null) return;
      if (state.theme === chatThemeRef.current) return; // auto-switch, not manual
      // Manual toggle detected — clear saved ref so leaving /chat won't override.
      savedPreChatThemeRef.current = null;
      chatThemeRef.current = state.theme;
    });
    return unsubscribe;
  }, [pathname]);

  // Route-transition effect: auto-switch on entering /chat, restore on leaving.
  // Dependencies are strictly [pathname] (never [theme]) so manual toggles
  // never trigger infinite loops or immediate reverts.
  useEffect(() => {
    const prev = prevPathnameRef.current;
    prevPathnameRef.current = pathname ?? null;

    // Skip the first render (prev is null) to avoid triggering on direct
    // navigation / refresh — respect the user's stored preference.
    if (prev === null) return;

    if (prev !== '/chat' && pathname === '/chat') {
      // Entering /chat
      const current = useThemeStore.getState().theme;
      if (current === 'dark') {
        savedPreChatThemeRef.current = 'dark';
        chatThemeRef.current = 'light';
        useThemeStore.getState().setTheme('light');
      } else {
        savedPreChatThemeRef.current = null;
        chatThemeRef.current = current;
      }
    } else if (prev === '/chat' && pathname !== '/chat') {
      // Leaving /chat
      if (savedPreChatThemeRef.current === 'dark') {
        useThemeStore.getState().setTheme('dark');
      }
      savedPreChatThemeRef.current = null;
      chatThemeRef.current = null;
    }
  }, [pathname]);

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