'use client';

import { useEffect, useState, useRef, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import { LoaderIcon } from '@/components/ui/loader-icon';

function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setAuth = useAuthStore((state) => state.setAuth);
  const [error, setError] = useState<string | null>(null);
  const code = searchParams.get('code');
  const calledRef = useRef(false);

  useEffect(() => {
    if (!code) {
      setError('No code provided from GitHub.');
      return;
    }

    if (calledRef.current) return;
    calledRef.current = true;

    const performExchange = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/v1/auth/github', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || 'Failed to authenticate with GitHub.');
        }

        const data = await res.json();
        setAuth(data.access_token, data.user);
        router.push('/dashboard');
      } catch (err: any) {
        console.error(err);
        setError(err.message || 'An error occurred during authentication.');
      }
    };

    performExchange();
  }, [code, router, setAuth]);

  return (
    <div className="w-full max-w-sm text-center space-y-6">
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center font-black text-2xl mx-auto shadow-[0_0_20px_rgba(59,130,246,0.4)]">
        R
      </div>

      {error ? (
        <div className="space-y-4">
          <div className="text-error font-semibold text-lg">Authentication Failed</div>
          <p className="text-muted-foreground text-sm">{error}</p>
          <button
            onClick={() => router.push('/login')}
            className="px-4 py-2 bg-muted hover:bg-muted/80 text-foreground rounded-lg text-sm transition-colors border border-border"
          >
            Back to Login
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-center gap-2">
            <LoaderIcon size={20} className="text-brand" />
            <span className="font-semibold text-lg">Authenticating with GitHub...</span>
          </div>
          <p className="text-muted-foreground text-sm">Setting up your secure session.</p>
        </div>
      )}
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background text-foreground p-6">
      <Suspense fallback={
        <div className="w-full max-w-sm text-center space-y-6">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center font-black text-2xl mx-auto shadow-[0_0_20px_rgba(59,130,246,0.4)]">
            R
          </div>
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-2">
              <LoaderIcon size={20} className="text-brand" />
              <span className="font-semibold text-lg">Loading secure session...</span>
            </div>
          </div>
        </div>
      }>
        <CallbackHandler />
      </Suspense>
    </div>
  );
}
