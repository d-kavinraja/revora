'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import Image from 'next/image';
import { motion, useReducedMotion } from 'framer-motion';
import axios from 'axios';
import { adminApi } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { ThemeToggle } from '@/components/ui/theme-toggle';
import { useAdminThemeStore } from '@/store/useAdminThemeStore';
import { isDefinitiveSessionRejection } from '@/lib/auth-session';

export default function AdminLoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const reducedMotion = useReducedMotion();
  const adminTheme = useAdminThemeStore((s) => s.theme);
  const toggleAdminTheme = useAdminThemeStore((s) => s.toggleTheme);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loginEstablished, setLoginEstablished] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    let established = loginEstablished;
    try {
      if (!established) {
        await adminApi.login({ username, password });
        established = true;
        setLoginEstablished(true);
      }
      // Never treat the credential response alone as authenticated. Confirm
      // that the first-party opaque cookie resolves to the persisted session.
      const session = await adminApi.session();
      queryClient.setQueryData(['admin', 'session'], session);
      router.replace('/admin');
    } catch (err) {
      let detail: string;
      if (established) {
        const rejected = isDefinitiveSessionRejection(err);
        if (rejected) setLoginEstablished(false);
        detail = rejected
          ? 'Signed in, but the admin session could not be confirmed. Please sign in again.'
          : 'Signed in, but the authentication service is temporarily unreachable. Retry session confirmation.';
      } else {
        detail =
          axios.isAxiosError(err) && typeof err.response?.data?.detail === 'string'
            ? err.response.data.detail
            : 'Unable to sign in. Please try again.';
      }
      setError(detail);
      setSubmitting(false);
    }
  };

  return (
    <div className="admin-grid min-h-screen w-full flex items-center justify-center bg-background relative overflow-hidden px-4">
      <div className="absolute top-4 right-4 z-10">
        <ThemeToggle theme={adminTheme} onToggle={toggleAdminTheme} className="h-9 w-9" />
      </div>

      <motion.div
        initial={reducedMotion ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reducedMotion ? 0 : 0.4, ease: 'easeOut' }}
        className="admin-tick admin-frame-elevated w-full max-w-sm p-8"
      >
        <div className="mb-8 flex flex-col items-center text-center">
          <Image
            src="/revora-logo.png"
            alt="Revora"
            width={44}
            height={44}
            style={{ width: 44, height: 44 }}
            className="mb-4 rounded-xl object-contain"
          />
          <p className="admin-eyebrow">Restricted access</p>
          <h1 className="mt-1.5 font-heading text-xl font-bold text-foreground">
            Admin console
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Sign in with your administrator credentials.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label
              htmlFor="admin-username"
              className="block text-sm font-medium text-foreground mb-1.5"
            >
              Username
            </label>
            <input
              id="admin-username"
              name="username"
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              disabled={submitting || loginEstablished}
              className="w-full h-11 rounded-lg border border-border bg-surface-2 px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 disabled:opacity-60"
              placeholder="admin"
            />
          </div>

          <div>
            <label
              htmlFor="admin-password"
              className="block text-sm font-medium text-foreground mb-1.5"
            >
              Password
            </label>
            <input
              id="admin-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={submitting || loginEstablished}
              className="w-full h-11 rounded-lg border border-border bg-surface-2 px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 disabled:opacity-60"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p
              role="alert"
              aria-live="polite"
              className="text-sm text-error bg-error/10 border border-error/30 rounded-lg px-3 py-2"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={
              submitting || (!loginEstablished && (!username || !password))
            }
            className="w-full h-11 rounded-lg bg-brand text-brand-foreground text-sm font-semibold cursor-pointer transition-colors hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {submitting ? (
              <>
                <LoaderIcon size={16} animate />
                {loginEstablished ? 'Confirming session…' : 'Signing in…'}
              </>
            ) : (
              loginEstablished ? 'Retry session confirmation' : 'Sign in'
            )}
          </button>
        </form>
      </motion.div>
    </div>
  );
}
