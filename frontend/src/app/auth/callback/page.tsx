'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { AuthBackdrop } from '@/components/auth/auth-stage';
import { SignInProgress, type Stage } from '@/components/auth/signin-progress';
import { restoreSession } from '@/lib/api';
import { startGitHubOAuth } from '@/lib/github-oauth';
import { isSafeInternalPath } from '@/lib/safe-redirect';
import { useAuthStore } from '@/store/useAuthStore';
import type { User } from '@/store/useAuthStore';

const NO_CODE_MESSAGE =
  'This sign-in link has no GitHub authorization attached. It may have expired, already been used, or been opened directly. Sign in again from the login page.';

const NETWORK_MESSAGE =
  'We could not reach the authentication service. Check your connection, then try again.';

function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setAuth = useAuthStore((state) => state.setAuth);
  const [stage, setStage] = useState<Stage>('restoring');
  const [error, setError] = useState<string | null>(null);
  const [failedStep, setFailedStep] = useState<number | null>(null);
  const [accountDisabled, setAccountDisabled] = useState(false);
  const [starting, setStarting] = useState(false);
  const calledRef = useRef(false);

  useEffect(() => {
    // Strict Mode runs effects twice on mount; the callback must be processed
    // exactly once (the authorization code is single-use).
    if (calledRef.current) return;
    calledRef.current = true;

    // Snapshot the one-shot OAuth parameters, then clean the address bar
    // immediately - before any async work. A GitHub authorization code is
    // single-use, so it must never be left in a URL that a refresh (or the
    // browser Back button) could re-submit.
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const oauthError = searchParams.get('error');
    const oauthErrorDescription = searchParams.get('error_description');
    window.history.replaceState(null, '', '/auth/callback');

    const goToApp = () => {
      // Return the user to the page they originally requested (the guard
      // appended ?redirect= and login stashed it); default to the dashboard.
      const intended = sessionStorage.getItem('revora_post_login_redirect');
      sessionStorage.removeItem('revora_post_login_redirect');
      router.push(isSafeInternalPath(intended) ? intended : '/dashboard');
    };

    const showError = (
      message: string,
      step: number | null = null,
      disabled = false,
    ) => {
      setFailedStep(step);
      setAccountDisabled(disabled);
      setError(message);
    };

    const performCallback = async () => {
      // 1. Session-first. The durable session is the backend-set HttpOnly
      // cookie, so an authenticated browser is restored instead of being
      // sent through the code exchange (or OAuth) again.
      const restored = await restoreSession();
      if (restored.ok) {
        setStage('redirecting');
        goToApp();
        return;
      }

      // 2. Cancelled authorization (the user pressed Cancel on GitHub).
      if (oauthError) {
        showError(
          'GitHub returned an error: ' +
            oauthError +
            (oauthErrorDescription ? ' (' + oauthErrorDescription + ')' : '') +
            (oauthError === 'access_denied'
              ? '. Authorization was cancelled. Please try again.'
              : ''),
          2,
        );
        return;
      }

      // 3. No code: a refresh after the URL was cleaned, an interrupted
      // attempt, or a direct visit. The session check above already proved
      // whether an authenticated session exists.
      if (!code) {
        const unreachable = restored.reason === 'unreachable';
        showError(unreachable ? NETWORK_MESSAGE : NO_CODE_MESSAGE, unreachable ? 1 : 2);
        return;
      }

      // 4. Exchange the single-use code via the same-origin BFF.
      // Same-origin route handler (app/api/auth/exchange) forwards to the
      // backend server-side and relays Set-Cookie - no cross-origin browser
      // hop, no CORS/SameSite failure modes.
      setStage('exchanging');
      let res: Response;
      try {
        res = await fetch('/api/auth/exchange', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code,
            redirect_uri: window.location.origin + '/auth/callback',
            // Login-CSRF proof minted by /auth/oauth/start before redirect.
            state: state ?? undefined,
          }),
        });
      } catch {
        showError(NETWORK_MESSAGE, 2);
        return;
      }

      const raw = await res.text();
      let payload: {
        access_token?: string;
        user?: User;
        detail?: string;
        code?: string;
        github_username?: string;
      } = {};
      try {
        payload = raw ? (JSON.parse(raw) as typeof payload) : {};
      } catch {
        showError(
          'Exchange failed (status ' + res.status + ', non-JSON response body).',
          2,
        );
        return;
      }

      if (!res.ok) {
        const isDisabled =
          payload.code === 'account_disabled' ||
          (res.status === 403 &&
            String(payload.detail ?? '').toLowerCase().includes('disabled'));
        if (isDisabled) {
          // Clear any in-memory session from a prior attempt (no server
          // revocation - the disabled account never got a usable session).
          void useAuthStore.getState().logout({ revoke: false });
          const handle = payload.github_username;
          showError(
            (handle
              ? 'The GitHub account @' +
                handle +
                ' is linked to a disabled Revora account and cannot sign in. Your account has been disabled. Please contact the administrator for assistance.'
              : 'Your account has been disabled. Please contact the administrator for assistance.') +
              '\nYou can try signing in with a different GitHub account.',
            2,
            true,
          );
          return;
        }

        // The code may already have been consumed by an earlier attempt (a
        // refresh, or a second tab). If a valid session now exists, this
        // browser is authenticated - finish as a success instead of showing a
        // misleading error.
        const recovery = await restoreSession();
        if (recovery.ok) {
          setStage('redirecting');
          goToApp();
          return;
        }
        showError(payload.detail || 'Exchange failed with status ' + res.status + '.', 2);
        return;
      }

      const { access_token, user } = payload;
      if (!access_token || !user) {
        showError(
          'Exchange succeeded but the response was incomplete. Please try again.',
          2,
        );
        return;
      }

      // 5. Never report a successful login on the exchange response alone:
      // confirm the backend-issued session cookie works (GET /auth/me) before
      // routing into the application.
      setStage('confirming');
      const confirmed = await restoreSession();
      if (!confirmed.ok) {
        showError(
          confirmed.reason === 'unreachable'
            ? 'Signed in, but the session could not be confirmed because the authentication service is unreachable. Please try again.'
            : 'Signed in, but the session could not be confirmed. Please sign in again.',
          3,
        );
        return;
      }

      // In-memory token for this tab only. The durable session is the
      // backend-set HttpOnly cookie - page JS never touches it.
      setAuth(access_token, user);
      setStage('redirecting');
      goToApp();
    };

    void performCallback();
  }, [router, searchParams, setAuth]);

  const retry = async () => {
    if (starting) return;
    setStarting(true);
    try {
      await startGitHubOAuth({ switchAccount: accountDisabled });
    } catch {
      setStarting(false);
      setError('Could not start GitHub sign-in. Please try again.');
    }
  };

  return (
    <SignInProgress
      stage={stage}
      error={error}
      failedStep={failedStep}
      accountDisabled={accountDisabled}
      starting={starting}
      onRetry={() => void retry()}
      onBack={() => router.push('/login')}
    />
  );
}

export default function AuthCallbackPage() {
  return (
    <main className="relative flex min-h-[calc(100dvh-var(--revora-announcement-height,0px))] w-full items-center justify-center px-4 py-10">
      <AuthBackdrop />
      <div className="relative z-10 w-full max-w-[420px]">
        <Suspense fallback={<SignInProgress stage="restoring" />}>
          <CallbackHandler />
        </Suspense>
      </div>
    </main>
  );
}
