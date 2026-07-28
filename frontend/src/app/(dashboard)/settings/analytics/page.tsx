'use client';

import { ActivityIcon } from 'lucide-react';

export default function AnalyticsPage() {
  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="flex flex-col items-center justify-center min-h-[50vh] text-center">
        <ActivityIcon size={48} className="text-muted-foreground mb-4" />
        <h1 className="text-2xl font-bold text-foreground mb-2">Analytics</h1>
        <p className="text-muted-foreground max-w-md">
          Analytics are temporarily disabled while we redesign model-level pricing.
          No data has been lost. This feature will be re-enabled in a future release.
        </p>
      </div>
    </div>
  );
}

