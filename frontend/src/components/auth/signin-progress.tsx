import Image from 'next/image';
import { Check, X } from 'lucide-react';

import { LoaderIcon } from '@/components/ui/loader-icon';
import { cn } from '@/lib/utils';

export type Stage = 'restoring' | 'exchanging' | 'confirming' | 'redirecting';

const STEPS = [
  {
    title: 'Checking for an existing session',
    detail: 'A valid Revora session is reused instead of asking GitHub again.',
  },
  {
    title: 'Verifying with GitHub',
    detail: 'Exchanging the authorization GitHub just returned.',
  },
  {
    title: 'Starting your session',
    detail: 'Confirming the secure session before opening your dashboard.',
  },
];

function summarizeFailure(failedStep: number | null, accountDisabled: boolean): string {
  if (accountDisabled) {
    return 'This Revora account has been disabled, so it cannot sign in.';
  }
  if (failedStep === 1) {
    return 'The authentication service could not be reached.';
  }
  if (failedStep === 3) {
    return 'You signed in, but the browser session could not be confirmed.';
  }
  return 'GitHub sign-in could not be completed.';
}

interface SignInProgressProps {
  stage: Stage;
  error?: string | null;
  failedStep?: number | null;
  accountDisabled?: boolean;
  starting?: boolean;
  onRetry?: () => void;
  onBack?: () => void;
}

export function SignInProgress({
  stage,
  error = null,
  failedStep = null,
  accountDisabled = false,
  starting = false,
  onRetry,
  onBack,
}: SignInProgressProps) {
  const stageIndex =
    stage === 'restoring' ? 0 : stage === 'exchanging' ? 1 : 2;
  const complete = stage === 'redirecting' && !error;
  const summary = summarizeFailure(failedStep, accountDisabled);
  const statusLabel = error
    ? 'Stopped'
    : complete
      ? 'Complete'
      : 'In progress';
  const ariaStatus = error
    ? 'Sign-in stopped. ' + summary
    : complete
      ? 'Sign-in complete. Opening your dashboard.'
      : STEPS[stageIndex].title;

  return (
    <div className="auth-rise auth-panel overflow-hidden p-6 sm:p-7">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Image
            src="/revora-logo.png"
            alt=""
            width={24}
            height={24}
            className="h-6 w-6 rounded-md object-contain"
          />
          <span className="font-heading text-sm font-semibold tracking-tight text-foreground">
            Revora
          </span>
        </div>
        <span className="inline-flex items-center gap-1.5 font-mono text-[10px] leading-none text-muted-foreground">
          <span
            className={cn(
              'h-1.5 w-1.5 shrink-0 rounded-full',
              error
                ? 'bg-error text-error'
                : complete
                  ? 'bg-success text-success'
                  : 'auth-pulse bg-brand text-brand',
            )}
            aria-hidden="true"
          />
          {statusLabel}
        </span>
      </div>

      <h1 className="mt-6 font-heading text-[26px] font-semibold leading-tight tracking-[-0.02em] text-foreground">
        {error ? (
          <>Sign-in didn&rsquo;t complete.</>
        ) : complete ? (
          <>You&rsquo;re in.</>
        ) : (
          'Signing you in.'
        )}
      </h1>
      <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
        {error
          ? summary
          : complete
            ? 'Opening your dashboard.'
            : 'This usually takes a few seconds. Keep this tab open.'}
      </p>

      <p className="sr-only" role="status" aria-live="polite">
        {ariaStatus}
      </p>

      <div className="relative mt-7">
        <span
          aria-hidden="true"
          className="absolute bottom-2 left-[9px] top-2 w-px bg-border"
        />
        <ol className="space-y-5" aria-label="Sign-in progress">
          {STEPS.map((step, index) => {
            const stepNumber = index + 1;
            // On failure, progress is measured by the step that failed, so the
            // steps before it read as complete no matter when the stage state
            // was last advanced.
            const progressIndex =
              error && failedStep ? failedStep - 1 : stageIndex;
            const isFailed = Boolean(error) && failedStep === stepNumber;
            const isDone = complete || index < progressIndex;
            const isActive = !error && !complete && index === stageIndex;

            return (
              <li
                key={step.title}
                className="relative flex items-start gap-3.5"
                aria-current={isActive ? 'step' : undefined}
              >
                <span
                  className={cn(
                    'relative z-[1] flex h-5 w-5 shrink-0 items-center justify-center rounded-full border bg-surface-1',
                    isFailed && 'border-error/40 text-error',
                    isDone && 'border-success/40 text-success',
                    isActive && 'border-brand/50 text-brand',
                    !isFailed && !isDone && !isActive && 'border-border text-muted-foreground',
                  )}
                >
                  {isFailed ? (
                    <X size={12} aria-hidden="true" />
                  ) : isDone ? (
                    <Check size={12} aria-hidden="true" />
                  ) : isActive ? (
                    <LoaderIcon size={12} animate />
                  ) : (
                    <span
                      className="h-1 w-1 rounded-full bg-muted-foreground/50"
                      aria-hidden="true"
                    />
                  )}
                </span>
                <span className="min-w-0 pt-0.5">
                  <span
                    className={cn(
                      'block text-[13px] font-medium leading-snug',
                      isDone || isFailed
                        ? 'text-foreground'
                        : 'text-muted-foreground',
                    )}
                  >
                    {step.title}
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-relaxed text-muted-foreground">
                    {step.detail}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      </div>

      {error && (
        <div
          role="alert"
          className="mt-6 border-l-2 border-error/50 pl-3.5"
        >
          <p className="text-[10px] font-semibold uppercase tracking-[0.09em] text-error">
            {accountDisabled ? 'Account disabled' : 'Details'}
          </p>
          <p className="mt-1.5 whitespace-pre-line text-xs leading-relaxed text-foreground/85">
            {error}
          </p>
        </div>
      )}

      {error && onRetry && onBack && (
        <div className="mt-5 flex flex-col gap-2">
          <button
            type="button"
            onClick={onRetry}
            disabled={starting}
            aria-busy={starting}
            className="flex h-11 w-full items-center justify-center gap-2.5 rounded-lg border border-transparent bg-brand text-[13px] font-semibold text-background shadow-[inset_0_1px_0_rgba(255,255,255,0.16)] transition-[background-color,box-shadow] duration-150 hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-1)] disabled:cursor-wait"
          >
            {starting ? <LoaderIcon size={16} animate /> : null}
            {accountDisabled
              ? 'Sign in with another account'
              : starting
                ? 'Connecting to GitHub'
                : 'Try signing in again'}
          </button>
          <button
            type="button"
            onClick={onBack}
            className="flex h-10 w-full items-center justify-center rounded-lg border border-transparent text-[13px] font-medium text-muted-foreground transition-colors hover:border-border hover:bg-surface-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-1)]"
          >
            Back to sign in
          </button>
        </div>
      )}
    </div>
  );
}
