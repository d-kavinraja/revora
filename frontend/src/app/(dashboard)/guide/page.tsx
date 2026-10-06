'use client';

import React from 'react';
import { StackedCards } from '@/components/ui/glass-cards';

export default function SetupGuidePage() {
  // Transparent on purpose: the (dashboard) layout already provides the
  // standard Revora page treatment (theme-aware bg-background shell plus
  // the shared DotGrid), exactly like the review/repositories/profile
  // pages. Do not add an opaque background here or it will cover it.
  return (
    <div className="w-full min-h-screen">
      <StackedCards />
    </div>
  );
}
