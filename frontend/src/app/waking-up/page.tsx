'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { checkHealth } from '@/lib/api';
import Lightfall from '@/components/ui/Lightfall';
import { Header } from '@/components/layout/header';
import { Footer } from '@/components/ui/footer';

const POLL_INTERVAL_MS = 3000;
const MAX_ATTEMPTS = 40; // ~2 minutes

function WakingUpContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect = searchParams.get('redirect') || '/dashboard';
  const [dots, setDots] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<'waking' | 'alive' | 'timeout'>('waking');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dotsRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Animate the dots
  useEffect(() => {
    dotsRef.current = setInterval(() => {
      setDots(d => d.length >= 3 ? '' : d + '.');
    }, 500);
    return () => { if (dotsRef.current) clearInterval(dotsRef.current); };
  }, []);

  // Poll the health endpoint
  useEffect(() => {
    // Immediately check once on mount
    checkHealth().then(alive => {
      if (alive) {
        setStatus('alive');
        return;
      }
    });

    intervalRef.current = setInterval(async () => {
      setAttempt(a => {
        const next = a + 1;
        if (next >= MAX_ATTEMPTS) {
          setStatus('timeout');
          if (intervalRef.current) clearInterval(intervalRef.current);
        }
        return next;
      });

      const alive = await checkHealth();
      if (alive) {
        setStatus('alive');
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    }, POLL_INTERVAL_MS);

    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  // Redirect once server is alive
  useEffect(() => {
    if (status === 'alive') {
      const t = setTimeout(() => router.replace(redirect), 1200);
      return () => clearTimeout(t);
    }
  }, [status, redirect, router]);

  const progressPct = Math.min((attempt / MAX_ATTEMPTS) * 100, 100);

  return (
    <div className="dark min-h-screen flex flex-col bg-background relative overflow-hidden">
      <Header hideThemeToggle={true} />

      <div className="flex-1 flex flex-col items-center justify-center relative w-full h-full">
        {/* Lightfall background (always dark mode configuration) */}
        <div className="absolute inset-0 z-0 opacity-80">
          <Lightfall
            colors={['#A6C8FF', '#5227FF', '#FF9FFC']}
            backgroundColor="#030712"
            speed={0.6}
            streakCount={6}
            streakWidth={1}
            streakLength={1.5}
            glow={0.5}
            density={0.7}
            twinkle={0}
            zoom={2.5}
            backgroundGlow={0.2}
            opacity={1}
            mouseInteraction={false}
            mouseStrength={0}
            mouseRadius={0}
          />
        </div>

        <div className="relative z-10 flex flex-col items-center gap-8 max-w-md w-full px-8 py-12 text-center rounded-3xl bg-black/20 backdrop-blur-[2px] border border-white/5 shadow-2xl shadow-black/50">
          {/* Logo / Icon */}
          <div className="relative">
            <div
              className="w-20 h-20 rounded-2xl flex items-center justify-center shadow-2xl"
              style={{ background: 'linear-gradient(135deg, #7c3aed, #3b82f6)' }}
            >
              {status === 'alive' ? (
                // Checkmark when alive
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              ) : status === 'timeout' ? (
                // Warning when timeout
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              ) : (
                // Server icon while waking
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2" y="2" width="20" height="8" rx="2" ry="2" /><rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
                  <line x1="6" y1="6" x2="6.01" y2="6" /><line x1="6" y1="18" x2="6.01" y2="18" />
                </svg>
              )}
            </div>
            {/* Pulse ring while waking */}
            {status === 'waking' && (
              <span className="absolute inset-0 rounded-2xl animate-ping opacity-30"
                style={{ background: 'linear-gradient(135deg, #7c3aed, #3b82f6)' }}
              />
            )}
          </div>

          {/* Text */}
          {status === 'alive' ? (
            <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
              <h1 className="text-2xl font-bold text-white drop-shadow-md">Server is Ready!</h1>
              <p className="text-white/80 text-sm mt-2">Redirecting you now{dots}</p>
            </div>
          ) : status === 'timeout' ? (
            <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
              <h1 className="text-2xl font-bold text-red-400 drop-shadow-md">Server Taking Too Long</h1>
              <p className="text-white/80 text-sm leading-relaxed mt-3">
                The server hasn't responded in 2 minutes. This can happen on the Render free tier during very high load.
              </p>
              <button
                onClick={() => { setAttempt(0); setStatus('waking'); }}
                className="mt-6 px-6 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:opacity-90 hover:scale-105 active:scale-95 cursor-pointer shadow-lg shadow-indigo-500/25"
                style={{ background: 'linear-gradient(135deg, #7c3aed, #3b82f6)' }}
              >
                Try Again
              </button>
            </div>
          ) : (
            <div className="animate-in fade-in slide-in-from-bottom-4 duration-1000">
              <h1 className="text-3xl font-bold text-white tracking-tight drop-shadow-md">
                Server is Starting or Server Down<span className="inline-block w-6 text-left">{dots}</span>
              </h1>
              <p className="text-white/80 text-sm mt-4 leading-relaxed max-w-[320px] mx-auto font-medium">
                Your Revora backend is waking up from sleep mode.<br />
                This usually takes <span className="text-white font-bold">30–60 seconds</span>.
              </p>
            </div>
          )}

          {/* Progress Bar & Status */}
          {status === 'waking' && (
            <div className="w-full max-w-sm mt-4 animate-in fade-in slide-in-from-bottom-6 duration-1000 delay-150 fill-mode-both">
              <div className="h-1.5 w-full rounded-full overflow-hidden bg-white/10 backdrop-blur-md">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${progressPct}%`,
                    background: 'linear-gradient(90deg, #7c3aed, #3b82f6)',
                  }}
                />
              </div>
              <p className="text-xs text-white/70 mt-3 font-medium">
                Checking every {POLL_INTERVAL_MS / 1000}s — attempt {attempt + 1} of {MAX_ATTEMPTS}
              </p>
            </div>
          )}

          {/* Educational Note */}
          {status === 'waking' && (
            <div className="mt-4 p-5 rounded-xl text-left border border-white/10 bg-black/40 backdrop-blur-md animate-in fade-in slide-in-from-bottom-8 duration-1000 delay-300 fill-mode-both shadow-inner">
              <div className="flex items-center gap-2 mb-2">
                <span role="img" aria-label="lightbulb">💡</span>
                <h3 className="font-semibold text-sm text-white">Why is this happening?</h3>
              </div>
              <p className="text-xs text-white/80 leading-relaxed">
                Free-tier Render services pause when inactive for 15 minutes to save resources.
                Once a request arrives, they automatically restart. You only see this page when the server is cold-starting.
              </p>
            </div>
          )}
        </div>
      </div>

      <Footer
        logoSrc="/icon.png"
        className="z-20 relative bg-background/95 backdrop-blur-xl border-t border-border shadow-[0_-8px_30px_rgba(0,0,0,0.12)]"
      />
    </div>
  );
}

export default function WakingUpPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-8 h-8 border-2 border-brand/30 border-t-brand rounded-full animate-spin" />
      </div>
    }>
      <WakingUpContent />
    </Suspense>
  );
}
