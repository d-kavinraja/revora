'use client';

import { useEffect, useState, useRef, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import type { User } from '@/store/useAuthStore';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { SoftAurora } from '@/components/ui/SoftAurora';
import { useThemeStore } from '@/store/useThemeStore';
import { isSafeInternalPath } from '@/lib/safe-redirect';
import { startGitHubOAuth } from '@/lib/github-oauth';
import { restoreSession } from '@/lib/api';
import { motion } from 'framer-motion';

const NO_CODE_MESSAGE =
  'No GitHub sign-in information was found. This happens when the sign-in page is refreshed, was already used, or was opened directly. Please sign in again from the login page.';

const NETWORK_MESSAGE =
  'Network error: Could not reach the authentication service. Please verify the backend is running and the frontend dev server can reach it, then try again.';

function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setAuth = useAuthStore((state) => state.setAuth);
  const [error, setError] = useState<string | null>(null);
  const [disabledHandle, setDisabledHandle] = useState<string | null>(null);
  const calledRef = useRef(false);

  useEffect(() => {
    // Strict Mode runs effects twice on mount; the callback must be processed
    // exactly once (the authorization code is single-use).
    if (calledRef.current) return;
    calledRef.current = true;

    // Snapshot the one-shot OAuth parameters, then clean the address bar
    // immediately — before any async work. A GitHub authorization code is
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

    const showError = (message: string, handle: string | null = null) => {
      setDisabledHandle(handle);
      setError(message);
    };

    const performCallback = async () => {
      // 1. Session-first. The durable session is the backend-set HttpOnly
      // cookie, so an authenticated browser is restored instead of being
      // sent through the code exchange (or OAuth) again.
      const restored = await restoreSession();
      if (restored.ok) {
        goToApp();
        return;
      }

      // 2. Cancelled authorization (the user pressed Cancel on GitHub).
      if (oauthError) {
        showError(
          `GitHub returned an error: ${oauthError}` +
            (oauthErrorDescription ? ` (${oauthErrorDescription})` : '') +
            (oauthError === 'access_denied'
              ? ' — authorization was cancelled. Please try again.'
              : ''),
        );
        return;
      }

      // 3. No code: a refresh after the URL was cleaned, an interrupted
      // attempt, or a direct visit. The session check above already proved
      // whether an authenticated session exists.
      if (!code) {
        showError(restored.reason === 'unreachable' ? NETWORK_MESSAGE : NO_CODE_MESSAGE);
        return;
      }

      // 4. Exchange the single-use code via the same-origin BFF.
      // Same-origin route handler (app/api/auth/exchange) forwards to the
      // backend server-side and relays Set-Cookie — no cross-origin browser
      // hop, no CORS/SameSite failure modes.
      let res: Response;
      try {
        res = await fetch('/api/auth/exchange', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code,
            redirect_uri: `${window.location.origin}/auth/callback`,
            // Login-CSRF proof minted by /auth/oauth/start before redirect.
            state: state ?? undefined,
          }),
        });
      } catch {
        showError(NETWORK_MESSAGE);
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
          `Exchange failed (status ${res.status}, non-JSON response body).`
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
          // revocation — the disabled account never got a usable session).
          void useAuthStore.getState().logout({ revoke: false });
          const handle = payload.github_username;
          showError(
            (handle
              ? `The GitHub account @${handle} is linked to a disabled Revora account and cannot sign in. Your account has been disabled. Please contact the administrator for assistance.`
              : 'Your account has been disabled. Please contact the administrator for assistance.') +
              '\nYou can try signing in with a different GitHub account.',
            handle ?? null,
          );
          return;
        }

        // The code may already have been consumed by an earlier attempt (a
        // refresh, or a second tab). If a valid session now exists, this
        // browser is authenticated — finish as a success instead of showing a
        // misleading error.
        const recovery = await restoreSession();
        if (recovery.ok) {
          goToApp();
          return;
        }
        showError(payload.detail || `Exchange failed with status ${res.status}.`);
        return;
      }

      const { access_token, user } = payload;
      if (!access_token || !user) {
        showError(
          'Exchange succeeded but the response was incomplete. Please try again.'
        );
        return;
      }

      // 5. Never report a successful login on the exchange response alone:
      // confirm the backend-issued session cookie works (GET /auth/me) before
      // routing into the application.
      const confirmed = await restoreSession();
      if (!confirmed.ok) {
        showError(
          confirmed.reason === 'unreachable'
            ? 'Signed in, but the session could not be confirmed because the authentication service is unreachable. Please try again.'
            : 'Signed in, but the session could not be confirmed. Please sign in again.'
        );
        return;
      }

      // In-memory token for this tab only. The durable session is the
      // backend-set HttpOnly cookie — page JS never touches it.
      setAuth(access_token, user);
      goToApp();
    };

    void performCallback();
  }, [router, searchParams, setAuth]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
      className="w-full max-w-md p-8 bg-white/10 dark:bg-black/20 backdrop-blur-2xl border border-white/30 dark:border-white/10 rounded-2xl shadow-[0_8px_32px_0_rgba(31,38,135,0.1)] dark:shadow-[0_8px_32px_0_rgba(0,0,0,0.5)] z-10 ring-1 ring-white/20 dark:ring-white/5 text-center space-y-6"
    >
      <img
        src="/revora-logo.png"
        alt="Revora Logo"
        className="w-14 h-14 rounded-2xl object-contain mx-auto"
      />

      {error ? (
        <div className="space-y-4" role="alert">
          <div className="text-error font-semibold text-lg">Authentication Failed</div>
          <p className="text-foreground/80 font-medium text-sm whitespace-pre-line">{error}</p>
          <div className="flex flex-col gap-2">
            {disabledHandle !== null || error.includes('disabled') ? (
              <button
                type="button"
                onClick={() => {
                  void startGitHubOAuth({ switchAccount: true }).catch(() => {
                    setError('Could not start GitHub sign-in. Please try again.');
                  });
                }}
                className="px-4 py-2 bg-[#24292e] hover:bg-[#2c3238] text-white rounded-lg text-sm transition-colors border border-white/10 cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
              >
                Try another GitHub account
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => router.push('/login')}
              className="px-4 py-2 bg-muted hover:bg-muted/80 text-foreground rounded-lg text-sm transition-colors border border-border cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
            >
              Back to Login
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-center gap-2">
            <LoaderIcon size={20} className="text-brand" animate />
            <span className="font-semibold text-lg text-foreground">Authenticating with GitHub...</span>
          </div>
          <p className="text-foreground/80 font-medium text-sm">Setting up your secure session.</p>
        </div>
      )}
    </motion.div>
  );
}

export default function AuthCallbackPage() {
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

  return (
    <main className="min-h-screen relative flex items-center justify-center p-4 overflow-hidden">
      {/* Background gradients and SoftAurora */}
      <div className="absolute inset-0 pointer-events-none z-0">
        <SoftAurora
          speed={0.6}
          scale={1.5}
          brightness={isLight ? 0.7 : 1.0}
          color1={isLight ? "#2563eb" : "#f7f7f7"}
          color2={isLight ? "#6366f1" : "#818cf8"}
          noiseFrequency={2.5}
          noiseAmplitude={1.0}
          bandHeight={0.5}
          bandSpread={1.0}
          octaveDecay={0.1}
          layerOffset={0}
          colorSpeed={1.0}
          enableMouseInteraction={true}
          mouseInfluence={0.25}
        />
      </div>
      <div className="absolute top-[15%] left-[25%] w-[35%] h-[35%] bg-brand/15 blur-[120px] rounded-full pointer-events-none z-0" />
      <div className="absolute bottom-[15%] right-[25%] w-[30%] h-[30%] bg-info/10 blur-[120px] rounded-full pointer-events-none z-0" />

      <Suspense fallback={
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="w-full max-w-md p-8 bg-white/10 dark:bg-black/20 backdrop-blur-2xl border border-white/30 dark:border-white/10 rounded-2xl shadow-[0_8px_32px_0_rgba(31,38,135,0.1)] dark:shadow-[0_8px_32px_0_rgba(0,0,0,0.5)] z-10 ring-1 ring-white/20 dark:ring-white/5 text-center space-y-6"
        >
          <img
            src="/revora-logo.png"
            alt="Revora Logo"
            className="w-14 h-14 rounded-2xl object-contain mx-auto"
          />
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-2">
              <LoaderIcon size={20} className="text-brand" animate />
              <span className="font-semibold text-lg text-foreground">Loading secure session...</span>
            </div>
          </div>
        </motion.div>
      }>
        <CallbackHandler />
      </Suspense>
    </main>
  );
}
