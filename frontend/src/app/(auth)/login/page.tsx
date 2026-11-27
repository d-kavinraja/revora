'use client';

import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
} from 'react';
import Link from 'next/link';
import { ArrowLeft, ArrowLeftRight, Info, ShieldCheck } from 'lucide-react';

import { AuthBackdrop } from '@/components/auth/auth-stage';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { useToast } from '@/components/ui/toaster';
import { checkHealth } from '@/lib/api';
import { isSafeInternalPath } from '@/lib/safe-redirect';
import { startGitHubOAuth } from '@/lib/github-oauth';
import { cn } from '@/lib/utils';

function subscribeToUrl(): () => void {
  // Static for the lifetime of this page; no subscription needed.
  return () => {};
}

type ServiceState = 'checking' | 'reachable' | 'unreachable';

const SERVICE_COPY: Record<ServiceState, string> = {
  checking: 'Checking auth service',
  reachable: 'Auth service reachable',
  unreachable: 'Auth service unreachable',
};

const SERVICE_DOT: Record<ServiceState, string> = {
  checking: 'bg-muted-foreground/50',
  reachable: 'bg-success',
  unreachable: 'bg-warning',
};

const GITHUB_MARK_PATH =
  'M12 .5C5.73.5.9 5.33.9 11.6c0 4.9 3.17 9.05 7.58 10.53.55.1.76-.24.76-.53v-1.87c-3.08.68-3.73-1.29-3.73-1.29-.51-1.29-1.24-1.63-1.24-1.63-1.01-.69.08-.68.08-.68 1.12.08 1.71 1.15 1.71 1.15 1 1.72 2.63 1.22 3.27.94.1-.73.39-1.24.71-1.52-2.46-.28-5.05-1.23-5.05-5.48 0-1.21.43-2.21 1.14-2.99-.11-.28-.49-1.41.11-2.94 0 0 .93-.3 3.05 1.15a10.5 10.5 0 0 1 5.55 0c2.12-1.45 3.05-1.15 3.05-1.15.6 1.53.22 2.66.11 2.94.71.78 1.14 1.78 1.14 2.99 0 4.26-2.6 5.19-5.07 5.47.4.35.76 1.03.76 2.08v3.09c0 .3.2.65.77.53A11.1 11.1 0 0 0 23.1 11.6C23.1 5.33 18.27.5 12 .5Z';

function GithubMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      className={className}
    >
      <path d={GITHUB_MARK_PATH} />
    </svg>
  );
}

// `--brand` lightens in dark mode while `--brand-foreground` stays near-white,
// which drops the label below 4.5:1. The page background is the safe on-brand
// ink: white on the deep light-theme indigo, near-black on the brighter dark one.
const PRIMARY_BUTTON = [
  'flex h-11 w-full items-center justify-center gap-2.5 rounded-lg',
  'border border-transparent bg-brand text-[13px] font-semibold text-background',
  'shadow-[inset_0_1px_0_rgba(255,255,255,0.16)]',
  'transition-[background-color,box-shadow,transform] duration-150',
  'hover:bg-brand-hover hover:shadow-[0_10px_26px_-18px_var(--brand)]',
  'active:translate-y-px',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand',
  'focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-1)]',
  'disabled:cursor-wait',
].join(' ');

const SECONDARY_BUTTON = [
  'flex h-10 w-full items-center justify-center gap-2 rounded-lg',
  'border border-transparent text-[13px] font-medium text-muted-foreground',
  'transition-colors duration-150',
  'hover:border-border hover:bg-surface-2 hover:text-foreground',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60',
  'focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-1)]',
  'disabled:cursor-wait disabled:opacity-50',
].join(' ');

export default function LoginPage() {
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [service, setService] = useState<ServiceState>('checking');
  const disabledReasonRef = useRef<boolean | null>(null);

  // The ?reason=disabled flag is one-shot: it is read once per mount (the effect
  // below rewrites the URL immediately afterwards), and the ref keeps that
  // snapshot stable across renders. Scoping it to the mount - rather than the
  // module - means a client-side navigation back to /login cannot inherit a
  // stale banner from an earlier disabled-account attempt.
  const getDisabledReason = () => {
    if (disabledReasonRef.current === null) {
      disabledReasonRef.current =
        typeof window !== 'undefined' &&
        new URLSearchParams(window.location.search).get('reason') === 'disabled';
    }
    return disabledReasonRef.current;
  };
  // The SSR snapshot is false, so React flips the banner on after hydration
  // without a mismatch; no effect sets state.
  const showDisabledReason = useSyncExternalStore(
    subscribeToUrl,
    getDisabledReason,
    () => false,
  );
  const disabledMessage = showDisabledReason
    ? 'Your account has been disabled. Please contact the administrator for assistance.'
    : null;
  const { toast } = useToast();
  // True once we have handed the browser off to GitHub. Used to tell an
  // in-flight start apart from a stale spinner after the user comes back.
  const redirectingRef = useRef(false);
  const resetTimerRef = useRef<number | null>(null);

  const releaseRedirect = () => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
    if (!redirectingRef.current) return;
    redirectingRef.current = false;
    setLoadingConfig(false);
  };

  /**
   * `startGitHubOAuth` ends with a full-page `location.href` navigation. If the
   * user cancels on GitHub and returns with the browser Back button, the page is
   * restored from the back/forward cache: the JS heap survives, so this
   * component's `loadingConfig` state survives too and the button would stay
   * permanently disabled. Reset on bfcache restore, on returning to the tab,
   * and via a timer as a final safety net.
   */
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) releaseRedirect();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') releaseRedirect();
    };

    window.addEventListener('pageshow', onPageShow);
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.removeEventListener('pageshow', onPageShow);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
        resetTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('reason') === 'disabled') {
      params.delete('reason');
      const qs = params.toString();
      window.history.replaceState(
        {},
        '',
        window.location.pathname + (qs ? '?' + qs : ''),
      );
    }
  }, []);

  // A quiet reachability readout: if the API is asleep, the user learns why
  // the GitHub hand-off is about to fail before they click.
  useEffect(() => {
    let cancelled = false;
    void checkHealth().then((alive) => {
      if (!cancelled) setService(alive ? 'reachable' : 'unreachable');
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleGitHubLogin = async (switchAccount = false) => {
    // Synchronous guard: a fast second click can land before React applies the
    // button's disabled attribute, and two concurrent OAuth starts would mint
    // two states - the second invalidating the first.
    if (redirectingRef.current) return;
    setLoadingConfig(true);
    redirectingRef.current = true;
    // Safety net: if the hand-off to GitHub never happens (navigation blocked,
    // popup stripped, network stalls), release the spinner so the button can
    // never stay disabled.
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
    }
    resetTimerRef.current = window.setTimeout(releaseRedirect, 10_000);
    try {
      // Remember where the user was headed (guards append ?redirect=) so the
      // OAuth round-trip can return them there instead of always going to the
      // dashboard. Only safe internal paths are kept; anything else is cleared.
      const intended = new URLSearchParams(window.location.search).get(
        'redirect',
      );
      if (isSafeInternalPath(intended)) {
        sessionStorage.setItem('revora_post_login_redirect', intended);
      } else {
        sessionStorage.removeItem('revora_post_login_redirect');
      }
      await startGitHubOAuth({ switchAccount });
    } catch (err) {
      console.error('Failed to start GitHub sign-in', err);
      releaseRedirect();
      toast({
        title: 'Failed to connect to the backend authorization service.',
        type: 'error',
      });
      setLoadingConfig(false);
    }
  };

  return (
    <div className="relative w-full">
      <AuthBackdrop />

      <div className="relative z-10 mx-auto grid w-full max-w-6xl items-center gap-10 px-6 py-10 sm:px-8 lg:grid-cols-[minmax(0,1fr)_404px] lg:gap-16 lg:py-14 xl:gap-24">
        {/* Sign-in control. Placed first on small screens so the task is
            reachable without scrolling past the product statement. */}
        <section
          className="auth-rise order-1 w-full lg:order-2"
          style={{ '--auth-delay': '120ms' } as CSSProperties}
          aria-labelledby="signin-title"
        >
          <div className="auth-panel overflow-hidden p-6 sm:p-7">
            <div className="flex items-center justify-between gap-4">
              <span className="text-[10px] font-semibold uppercase tracking-[0.11em] text-muted-foreground">
                Sign in
              </span>
              <span className="inline-flex items-center gap-1.5 font-mono text-[10px] leading-none text-muted-foreground">
                <span
                  className={cn(
                    'h-1.5 w-1.5 shrink-0 rounded-full',
                    SERVICE_DOT[service],
                  )}
                  aria-hidden="true"
                />
                {SERVICE_COPY[service]}
              </span>
            </div>

            <h2
              id="signin-title"
              className="mt-4 text-[21px] font-semibold leading-tight tracking-[-0.01em] text-foreground"
            >
              Continue with GitHub
            </h2>
            <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
              {disabledMessage
                ? 'Choose a different account to continue.'
                : 'Use the account that installed Revora-PR.'}
            </p>

            {disabledMessage && (
              <div role="alert" className="mt-5 border-l-2 border-error/50 pl-3.5">
                <p className="text-[10px] font-semibold uppercase tracking-[0.09em] text-error">
                  Account disabled
                </p>
                <p className="mt-1.5 text-xs leading-relaxed text-foreground/85">
                  {disabledMessage}
                </p>
              </div>
            )}

            <div className="mt-6 space-y-2">
              <button
                type="button"
                onClick={() => void handleGitHubLogin(showDisabledReason)}
                aria-busy={loadingConfig}
                disabled={loadingConfig}
                className={PRIMARY_BUTTON}
              >
                {loadingConfig ? (
                  <LoaderIcon size={16} animate />
                ) : (
                  <GithubMark className="h-[18px] w-[18px]" />
                )}
                {loadingConfig
                  ? 'Connecting to GitHub'
                  : showDisabledReason
                    ? 'Sign in with another account'
                    : 'Sign in with GitHub'}
              </button>

              {!showDisabledReason && (
                <button
                  type="button"
                  onClick={() => void handleGitHubLogin(true)}
                  aria-busy={loadingConfig}
                  disabled={loadingConfig}
                  className={SECONDARY_BUTTON}
                >
                  <ArrowLeftRight size={14} aria-hidden="true" />
                  Use a different GitHub account
                </button>
              )}
            </div>

            <div className="mt-6 space-y-2.5 border-t border-border pt-4">
              <p className="flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground">
                <ShieldCheck
                  size={13}
                  className="mt-px shrink-0 text-success"
                  aria-hidden="true"
                />
                <span>OAuth only. Revora never sees your password.</span>
              </p>
              <p className="flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground">
                <Info
                  size={13}
                  className="mt-px shrink-0 text-info"
                  aria-hidden="true"
                />
                <span>Password sign-in isn&rsquo;t available yet.</span>
              </p>
              {service === 'unreachable' && (
                <p className="text-[11px] leading-relaxed text-warning">
                  The API is unreachable, so sign-in may fail until it is back.
                </p>
              )}
            </div>
          </div>

          <div className="mt-4 flex justify-center">
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]"
            >
              <ArrowLeft size={13} aria-hidden="true" />
              Back to home
            </Link>
          </div>
        </section>

        <section
          className="order-2 max-w-xl lg:order-1"
          aria-labelledby="signin-headline"
        >
          <h1
            id="signin-headline"
            className="font-heading text-[clamp(2rem,4.2vw,3.125rem)] font-bold leading-[1.06] tracking-[-0.03em] text-pretty text-foreground"
          >
            Reviews that read the whole repository.
          </h1>
          <p className="mt-5 max-w-[46ch] text-[15px] leading-relaxed text-muted-foreground">
            Revora reviews pull requests with full repository context, then
            checks every finding against the code before it posts. Bring your
            own model key and keep the workflow you already have.
          </p>

          <dl className="mt-10 grid grid-cols-3 border-t border-border">
            {[
              { value: '17', label: 'Repository detectors' },
              { value: '7', label: 'Code-graph types' },
              { value: 'BYOK', label: 'Encrypted provider keys' },
            ].map((item, index) => (
              <div
                key={item.label}
                className={cn(
                  'flex flex-col-reverse pt-4',
                  index > 0 ? 'border-l border-border pl-4' : 'pr-4',
                )}
              >
                <dt className="mt-2 text-[10px] font-semibold uppercase leading-[1.35] tracking-[0.09em] text-muted-foreground">
                  {item.label}
                </dt>
                <dd className="font-mono text-[19px] font-medium leading-none tracking-tight text-foreground">
                  {item.value}
                </dd>
              </div>
            ))}
          </dl>

          <div className="mt-9 flex items-start gap-3 border-t border-border pt-5">
            <GithubMark className="mt-0.5 h-4 w-4 shrink-0 text-foreground/60" />
            <p className="max-w-[46ch] text-xs leading-relaxed text-muted-foreground">
              Access comes through the{' '}
              <span className="whitespace-nowrap font-medium text-foreground">
                Revora-PR
              </span>{' '}
              GitHub App. You choose which repositories it reads, and you can
              revoke access from GitHub at any time.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
