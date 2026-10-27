'use client';

import Link from 'next/link';
import { Info } from 'lucide-react';
import { FadeIn } from './_components/FadeIn';
import { ModelCard } from './_components/ModelCard';
import { ComingSoonCard } from './_components/ComingSoonCard';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';

// Main content only — the sidebar/header chrome comes from (dashboard)/layout.tsx.
// Revora's own trained models launch here; new model cards are appended beside
// MouthMapCard. Third-party BYOK providers live under Settings, not here.
export default function ModelLabPage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'model_lab');

  if (status !== 'enabled') {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable status={status} message={message} title="Model Lab is unavailable" />
      </div>
    );
  }

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="text-xs text-foreground/60">
        <Link href="/dashboard" className="hover:text-foreground transition-colors">
          Home
        </Link>
        <span className="mx-1.5" aria-hidden="true">
          &gt;
        </span>
        <span aria-current="page" className="text-foreground font-medium">
          Model Lab
        </span>
      </nav>

      {/* Page header */}
      <FadeIn className="mt-3 md:mt-4">
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight">Model Lab</h1>
        <p className="text-muted-foreground text-sm mt-1.5 leading-relaxed">
          Explore and test Revora&apos;s own trained AI models, free to use.
        </p>
      </FadeIn>

      {/* Model cards */}
      <div className="grid gap-4 md:gap-5 md:grid-cols-2 items-stretch mt-5 md:mt-7">
        <FadeIn delay={0.05} className="h-full">
          <ModelCard />
        </FadeIn>
        <FadeIn delay={0.11} className="h-full">
          <ComingSoonCard />
        </FadeIn>
      </div>

      {/* Footer note */}
      <FadeIn delay={0.17}>
        <p className="flex items-start gap-2 text-xs text-muted-foreground leading-relaxed mt-6 md:mt-8 max-w-[70ch]">
          <Info size={14} className="shrink-0 mt-px" aria-hidden="true" />
          <span>
            Free to use during the beta trial. Subject to fair-use limits and rate limiting.{' '}
            <Link
              href="/guide"
              className="text-brand hover:text-brand-hover font-medium transition-colors inline-flex items-center gap-1"
            >
              Learn more
              <span aria-hidden="true">&rarr;</span>
            </Link>
          </span>
        </p>
      </FadeIn>
    </div>
  );
}
