'use client';

import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Sidebar } from '@/components/layout/sidebar';
import { DotGrid } from '@/components/ui/DotGrid';
import TargetCursor from '@/components/ui/TargetCursor';
import { useThemeStore } from '@/store/useThemeStore';
import { checkHealth } from '@/lib/api';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { theme } = useThemeStore();
  const isLight = theme === 'light';
  const router = useRouter();
  const pathname = usePathname();

  // On mount, check if the backend is alive.
  // If it's sleeping (Render free tier), send user to the wake-up splash page.
  useEffect(() => {
    checkHealth().then(alive => {
      if (!alive) {
        router.replace(`/waking-up?redirect=${encodeURIComponent(pathname)}`);
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run once on mount

  return (
    <div className="min-h-screen bg-background text-foreground flex w-full relative">
      <TargetCursor
        spinDuration={2}
        hideDefaultCursor={true}
        parallaxOn={true}
        cursorColor={isLight ? '#6366f1' : '#a855f7'}
        cursorColorOnTarget={isLight ? '#4338ca' : '#d8b4fe'}
      />
      {/* Background DotGrid */}
      <div className="fixed inset-0 z-0 pointer-events-none">
        <DotGrid
          dotSize={8}
          gap={24}
          baseColor={isLight ? '#e2e8f0' : '#1e293b'}
          activeColor={isLight ? '#6366f1' : '#8b5cf6'}
          proximity={120}
          shockRadius={200}
          shockStrength={5}
          resistance={750}
          returnDuration={1.5}
          style={{}}
        />
      </div>

      <Sidebar />
      <main className="flex-1 min-w-0 overflow-auto z-10 pt-16 md:pt-0">
        {children}
      </main>
    </div>
  );
}
