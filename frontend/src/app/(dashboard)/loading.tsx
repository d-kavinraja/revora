'use client';

import { LoaderIcon } from '@/components/ui/loader-icon';

export default function DashboardLoading() {
  return (
    <div className="w-full h-[calc(100vh-64px)] flex items-center justify-center">
      <div className="flex flex-col items-center gap-4 text-muted-foreground">
        <LoaderIcon size={32} className="text-brand" animate />
        <p className="text-sm font-medium animate-pulse">Loading dashboard...</p>
      </div>
    </div>
  );
}
