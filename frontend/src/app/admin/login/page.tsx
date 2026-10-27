'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import Image from 'next/image';
import { motion } from 'framer-motion';
import axios from 'axios';
import { adminApi } from '@/lib/api';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { ThemeToggle } from '@/components/ui/theme-toggle';
import { useAdminThemeStore } from '@/store/useAdminThemeStore';

export default function AdminLoginPage() {
  const router = useRouter();
  const adminTheme = useAdminThemeStore((s) => s.theme);
  const toggleAdminTheme = useAdminThemeStore((s) => s.toggleTheme);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await adminApi.login({ username, password });
      router.replace('/admin');
    } catch (err) {
      const detail =
        axios.isAxiosError(err) && typeof err.response?.data?.detail === 'string'
          ? err.response.data.detail
          : 'Unable to sign in. Please try again.';
      setError(detail);
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-background relative overflow-hidden px-4">
      <div className="absolute top-4 right-4 z-10">
        <ThemeToggle theme={adminTheme} onToggle={toggleAdminTheme} className="h-9 w-9" />
      </div>
      <div className="absolute top-[10%] left-[20%] w-[40%] h-[40%] bg-brand/10 blur-[140px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[10%] right-[20%] w-[35%] h-[35%] bg-info/10 blur-[140px] rounded-full pointer-events-none" />

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        className="w-full max-w-sm rounded-2xl border border-border bg-surface-1/90 backdrop-blur-xl p-8 shadow-2xl"
      >
        <div className="flex flex-col items-center text-center mb-8">
          <Image
            src="/revora-logo.png"
            alt="Revora"
            width={44}
            height={44}
            className="rounded-xl object-contain mb-4"
          />
          <h1 className="text-xl font-bold text-foreground">Admin Console</h1>
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
              disabled={submitting}
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
              disabled={submitting}
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
            disabled={submitting || !username || !password}
            className="w-full h-11 rounded-lg bg-brand text-brand-foreground text-sm font-semibold cursor-pointer transition-colors hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {submitting ? (
              <>
                <LoaderIcon size={16} animate />
                Signing in…
              </>
            ) : (
              'Sign in'
            )}
          </button>
        </form>
      </motion.div>
    </div>
  );
}
