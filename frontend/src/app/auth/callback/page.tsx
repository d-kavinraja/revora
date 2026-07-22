'use client';

import { useEffect, useState, useRef, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { SoftAurora } from '@/components/ui/SoftAurora';
import { useThemeStore } from '@/store/useThemeStore';
import { motion } from 'framer-motion';

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
        const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';
        const res = await fetch(`${apiBase}/auth/github`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code,
            redirect_uri: `${window.location.origin}/auth/callback`
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || 'Failed to authenticate with GitHub.');
        }

        const data = await res.json();
        setAuth(data.access_token, data.user);
        document.cookie = `revora_auth_token=${data.access_token}; path=/; max-age=86400; SameSite=Lax`;
        router.push('/dashboard');
      } catch (err: any) {
        console.error(err);
        setError(err.message || 'An error occurred during authentication.');
      }
    };

    performExchange();
  }, [code, router, setAuth]);

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
        className="w-14 h-14 rounded-2xl object-contain mx-auto shadow-[0_0_20px_rgba(99,102,241,0.35)]"
      />

      {error ? (
        <div className="space-y-4">
          <div className="text-error font-semibold text-lg drop-shadow-sm">Authentication Failed</div>
          <p className="text-foreground/80 font-medium text-sm drop-shadow-sm">{error}</p>
          <button
            onClick={() => router.push('/login')}
            className="px-4 py-2 bg-muted hover:bg-muted/80 text-foreground rounded-lg text-sm transition-colors border border-border cursor-pointer shadow-sm"
          >
            Back to Login
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-center gap-2">
            <LoaderIcon size={20} className="text-brand" animate />
            <span className="font-semibold text-lg text-foreground drop-shadow-sm">Authenticating with GitHub...</span>
          </div>
          <p className="text-foreground/80 font-medium text-sm drop-shadow-sm">Setting up your secure session.</p>
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
          color2={isLight ? "#7c3aed" : "#e100ff"}
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
      <div className="absolute bottom-[15%] right-[25%] w-[30%] h-[30%] bg-purple-600/10 blur-[120px] rounded-full pointer-events-none z-0" />

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
            className="w-14 h-14 rounded-2xl object-contain mx-auto shadow-[0_0_20px_rgba(99,102,241,0.35)]"
          />
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-2">
              <LoaderIcon size={20} className="text-brand" animate />
              <span className="font-semibold text-lg text-foreground drop-shadow-sm">Loading secure session...</span>
            </div>
          </div>
        </motion.div>
      }>
        <CallbackHandler />
      </Suspense>
    </main>
  );
}
