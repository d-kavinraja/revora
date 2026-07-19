'use client';

import { WeaveSpinner } from '@/components/ui/weave-spinner';

export default function SettingsLoading() {
  return (
    <div className="w-full h-full flex items-center justify-center min-h-[400px]">
      <div className="flex flex-col items-center gap-4 text-muted-foreground scale-75">
        <WeaveSpinner />
        <p className="text-sm font-medium animate-pulse mt-4">Loading settings...</p>
      </div>
    </div>
  );
}
