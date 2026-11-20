'use client';

import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { OnboardingTour } from '@/components/onboarding/onboarding-tour';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';

export default function SetupGuidePage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'guide');

  if (status !== 'enabled') {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable status={status} message={message} title="Setup Guide is unavailable" variant="page" />
      </div>
    );
  }

  return (
    <div className="w-full min-h-[calc(100dvh-var(--revora-announcement-height,0px))] p-4 md:p-6 lg:p-8">
      <OnboardingTour open={true} onClose={() => {}} mode="page" />
    </div>
  );
}