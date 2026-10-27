'use client';

import React from 'react';
import { StackedCards } from '@/components/ui/glass-cards';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';

export default function SetupGuidePage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'guide');

  if (status !== 'enabled') {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable status={status} message={message} title="Setup Guide is unavailable" />
      </div>
    );
  }

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
