'use client';

import { Sidebar } from '@/components/layout/sidebar';
import { DotGrid } from '@/components/ui/DotGrid';
import TargetCursor from '@/components/ui/TargetCursor';
import { useThemeStore } from '@/store/useThemeStore';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

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
        />
      </div>

      <Sidebar />
      <main className="flex-1 min-w-0 overflow-auto z-10 pt-16 md:pt-0">
        {children}
      </main>
    </div>
  );
}
