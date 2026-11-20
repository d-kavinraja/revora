'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ChevronLeft, ChevronRight, HelpCircle, CheckCircle2 } from 'lucide-react';
import { Modal } from '@/components/shared/modal';
import { ONBOARDING_STEPS, type OnboardingStep } from '@/lib/onboarding-steps';

interface OnboardingTourProps {
  open: boolean;
  onClose: () => void;
  mode?: 'modal' | 'page';
}

export function OnboardingTour({ open, onClose, mode = 'modal' }: OnboardingTourProps) {
  const [stepIndex, setStepIndex] = useState(0);
  const total = ONBOARDING_STEPS.length;
  const step: OnboardingStep = ONBOARDING_STEPS[stepIndex];
  const isLast = stepIndex === total - 1;
  const isFirst = stepIndex === 0;

  // Reset to the first step whenever the tour closes (including Escape/backdrop)
  // so reopening starts from step 1.
  const handleClose = () => {
    setStepIndex(0);
    onClose();
  };

  const goNext = () => {
    if (isLast) handleClose();
    else setStepIndex((i) => Math.min(i + 1, total - 1));
  };
  const goPrev = () => setStepIndex((i) => Math.max(i - 1, 0));
  const skip = handleClose;

  const body = (
    <div className="space-y-5">
      {/* Progress */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Step {stepIndex + 1} of {total}
        </span>
        <div className="h-1.5 w-32 overflow-hidden rounded-full bg-surface-2">
          <div
            className="h-full rounded-full bg-brand transition-all duration-300"
            style={{ width: `${((stepIndex + 1) / total) * 100}%` }}
            role="progressbar"
            aria-valuenow={stepIndex + 1}
            aria-valuemin={1}
            aria-valuemax={total}
          />
        </div>
      </div>

      {/* Visual + content */}
      <div className="rounded-xl border border-border bg-surface-2/40 p-4">
        <div className="mb-3 flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand/10 text-sm font-bold text-brand">
            {stepIndex + 1}
          </span>
          <h3 className="text-base font-semibold text-foreground">{step.title}</h3>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">{step.description}</p>

        {step.id === 'access' && (
          <ol className="mt-4 space-y-2 text-sm">
            {step.bullets?.map((b, i) => (
              <li key={i} className="flex items-start gap-2">
                <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-brand" />
                <span className="text-foreground/80">{b}</span>
              </li>
            ))}
          </ol>
        )}

        {step.id !== 'access' && step.bullets && (
          <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-foreground/80">
            {step.bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        )}
      </div>

      {/* CTAs */}
      <div className="flex flex-wrap items-center gap-2">
        {step.cta && (
          step.cta.external ? (
            <a
              href={step.cta.href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-brand-foreground transition-colors hover:bg-brand/90"
            >
              {step.cta.label}
            </a>
          ) : (
            <Link
              href={step.cta.href}
              onClick={handleClose}
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-brand-foreground transition-colors hover:bg-brand/90"
            >
              {step.cta.label}
            </Link>
          )
        )}
        {step.secondaryCta && (
          <Link
            href={step.secondaryCta.href}
            onClick={handleClose}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:border-brand/40"
          >
            {step.secondaryCta.label}
          </Link>
        )}
      </div>
    </div>
  );

  if (mode === 'page') {
    return (
      <div className="w-full max-w-2xl mx-auto">
        <div className="rounded-xl border border-border bg-surface-1 p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <HelpCircle size={20} className="text-brand" />
            <h1 className="text-xl font-bold text-foreground">Setup Guide</h1>
          </div>
          {body}
          <div className="mt-6 flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={goPrev}
              disabled={isFirst}
              className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-brand/40 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={14} /> Previous
            </button>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleClose}
                className="rounded-lg px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                Skip
              </button>
              <button
                type="button"
                onClick={goNext}
                className="inline-flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-brand-foreground transition-colors hover:bg-brand/90"
              >
                {isLast ? 'Done' : 'Next'} <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <Modal open={open} onClose={handleClose} title="Welcome to Revora" width="max-w-2xl">
      {body}
      <div className="mt-6 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={goPrev}
          disabled={isFirst}
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-brand/40 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ChevronLeft size={14} /> Previous
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={skip}
            className="rounded-lg px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Skip Tour
          </button>
          <button
            type="button"
            onClick={goNext}
            className="inline-flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-brand-foreground transition-colors hover:bg-brand/90"
          >
            {isLast ? 'Done' : 'Next'} <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function OnboardingHelpButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Open setup tour"
      title="Setup tour"
      className="fixed right-4 z-50 flex h-10 w-10 items-center justify-center rounded-full border border-border bg-surface-1 text-muted-foreground shadow-md transition-[top] transition-[top_0.2s_ease-out,colors] hover:bg-surface-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      style={{ top: 'calc(var(--revora-announcement-height, 0px) + 1rem)' }}
    >
      <HelpCircle size={18} />
    </button>
  );
}