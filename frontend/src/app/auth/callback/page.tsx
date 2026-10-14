'use client';

import { useEffect, useState, useRef, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import type { User } from '@/store/useAuthStore';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { SoftAurora } from '@/components/ui/SoftAurora';
import { useThemeStore } from '@/store/useThemeStore';
import { isSafeInternalPath } from '@/lib/safe-redirect';
import { motion } from 'framer-motion';

function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setAuth = useAuthStore((state) => state.setAuth);
  const code = searchParams.get('code');
  const oauthError = searchParams.get('error');
  const oauthErrorDescription = searchParams.get('error_description');
  // URL-derived failures surface immediately (no effect round-trip).
  const urlError = oauthError
    ? `GitHub returned an error: ${oauthError}` +
      (oauthErrorDescription ? ` (${oauthErrorDescription})` : '') +
      (oauthError === 'access_denied'
        ? ' — authorization was cancelled. Please try again.'
        : '')
    : !code
      ? 'No code provided from GitHub. Check browser console for URL details.'
      : null;
  const [error, setError] = useState<string | null>(urlError);
  const calledRef = useRef(false);

  useEffect(() => {
    // DEBUG: Log all search params to see what GitHub sent back
    console.log('[Callback] Full URL:', window.location.href);
    console.log('[Callback] Search params:', Object.fromEntries(searchParams.entries()));
    console.log('[Callback] Code param:', code);
    console.log('[Callback] State param:', searchParams.get('state'));

    if (urlError) {
      return;
    }

    if (calledRef.current) return;
    calledRef.current = true;

    const performExchange = async () => {
      try {
        console.log('[Callback] Exchanging code for token via same-origin BFF...', { code: code?.slice(0, 10) + '...' });
        // Same-origin route handler (app/api/auth/exchange) forwards to the
        // backend server-side and relays Set-Cookie — no cross-origin browser
        // hop, no CORS/SameSite failure modes.
        const res = await fetch('/api/auth/exchange', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code,
            redirect_uri: `${window.location.origin}/auth/callback`,
            // Login-CSRF proof minted by /auth/oauth/start before redirect.
            state: searchParams.get('state') ?? undefined,
          }),
        });

        console.log('[Callback] Exchange response:', res.status, res.statusText);

        const raw = await res.text();
        let payload: { access_token?: string; user?: User; detail?: string } = {};
        try {
          payload = raw ? (JSON.parse(raw) as typeof payload) : {};
        } catch {
          throw new Error(
            `Exchange failed (status ${res.status}, non-JSON response body).`
          );
        }

        if (!res.ok) {
          console.error('[Callback] Exchange failed:', payload);
          throw new Error(payload.detail || `Exchange failed with status ${res.status}.`);
        }

        const { access_token, user } = payload;
        if (!access_token || !user) {
          throw new Error(
            'Exchange succeeded but the response was incomplete. Please try again.'
          );
        }
        console.log('[Callback] Exchange successful, user:', user.email);
        // In-memory token for this tab only. The durable session is the
        // backend-set HttpOnly cookie — page JS never touches it.
        setAuth(access_token, user);
        // Return the user to the page they originally requested (the guard
        // appended ?redirect= and login stashed it); default to the dashboard.
        const intended = sessionStorage.getItem('revora_post_login_redirect');
        sessionStorage.removeItem('revora_post_login_redirect');
        router.push(isSafeInternalPath(intended) ? intended : '/dashboard');
      } catch (err: unknown) {
        console.error('[Callback] Auth exchange failed:', err);
        let message =
          err instanceof Error && err.message
            ? err.message
            : 'An error occurred during authentication.';
        if (message === 'Failed to fetch' || message.includes('NetworkError')) {
          message =
            'Network error: Could not reach the authentication service. ' +
            'Please verify the frontend dev server is running and reload the page.';
        }
        setError(message);
      }
    };

    performExchange();
  }, [code, router, setAuth, searchParams, urlError]);

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
        <div className="space-y-4">
          <div className="text-error font-semibold text-lg">Authentication Failed</div>
          <p className="text-foreground/80 font-medium text-sm">{error}</p>
          <button
            onClick={() => router.push('/login')}
            className="px-4 py-2 bg-muted hover:bg-muted/80 text-foreground rounded-lg text-sm transition-colors border border-border cursor-pointer"
          >
            Back to Login
          </button>
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
