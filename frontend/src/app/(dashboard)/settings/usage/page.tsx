'use client';

import { ChartBarIcon } from 'lucide-react';

export default function UsagePage() {
  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="flex flex-col items-center justify-center min-h-[50vh] text-center">
        <ChartBarIcon size={48} className="text-muted-foreground mb-4" />
        <h1 className="text-2xl font-bold text-foreground mb-2">Usage & Costs</h1>
        <p className="text-muted-foreground max-w-md">
          Usage analytics are temporarily disabled while we redesign model-level pricing.
          No data has been lost. This feature will be re-enabled in a future release.
        </p>
      </div>
    </div>
  );
}


