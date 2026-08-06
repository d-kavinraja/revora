'use client';

import { useEffect, useState, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { checkHealth } from '@/lib/api';

const POLL_INTERVAL_MS = 15000;     // Check every 15s during normal usage
const RECOVERY_INTERVAL_MS = 3000;  // Check every 3s when server is down
const FAILURE_THRESHOLD = 3;        // Require 3 consecutive failures before showing overlay

// Pages where we should NOT show the overlay or redirect (splash page itself, OAuth callback)
const EXCLUDED_PATHS = ['/waking-up', '/auth/callback'];

type ServerState = 'unknown' | 'alive' | 'down';

export function ServerStatusOverlay() {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [serverState, setServerState] = useState<ServerState>('unknown');
  const [dots, setDots] = useState('');
  const [recovering, setRecovering] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dotsRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isInitialMount = useRef(true);
  const wasDown = useRef(false);
  const failureCount = useRef(0);

  const isExcluded = EXCLUDED_PATHS.some(p => pathname === p || pathname.startsWith('/auth'));

  // Animated dots for the message
  useEffect(() => {
    if (serverState === 'down') {
      dotsRef.current = setInterval(() => {
        setDots(d => d.length >= 3 ? '' : d + '.');
      }, 500);
    }
    return () => { if (dotsRef.current) clearInterval(dotsRef.current); };
  }, [serverState]);

  useEffect(() => {
    if (isExcluded) return;

    const runCheck = async () => {
      const alive = await checkHealth();
      if (alive) {
        failureCount.current = 0; // Reset on success
        if (serverState === 'down' || wasDown.current) {
          // Server just recovered — show "recovered" state briefly, then auto-refresh all data
          wasDown.current = false;
          setRecovering(true);
          setTimeout(() => {
            setServerState('alive');
            setRecovering(false);
            // Invalidate ALL cached queries so pages re-fetch fresh data automatically
            queryClient.invalidateQueries();
            // Force Next.js router cache refresh
            router.refresh();
          }, 1500);
        } else {
          setServerState('alive');
        }
      } else {
        failureCount.current += 1;
        if (isInitialMount.current) {
          // If the server is asleep on the very first page load of any route, redirect to splash page
          router.replace(`/waking-up?redirect=${encodeURIComponent(pathname)}`);
        } else if (failureCount.current >= FAILURE_THRESHOLD) {
          // Only show the overlay after FAILURE_THRESHOLD consecutive failures
          // This prevents false positives when the backend is busy with a long LLM call
          wasDown.current = true;
          setServerState('down');
        }
      }
      isInitialMount.current = false;
    };

    // Run immediately on mount / pathname change
    runCheck();

    // Poll at faster rate when server is down, slower when alive
    const interval = serverState === 'down' ? RECOVERY_INTERVAL_MS : POLL_INTERVAL_MS;
    intervalRef.current = setInterval(runCheck, interval);

    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, serverState, isExcluded]);

  // Don't show anything on excluded pages or when server is alive
  if (isExcluded || serverState === 'alive' || serverState === 'unknown') return null;

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center"
      style={{
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        backgroundColor: 'rgba(0, 0, 0, 0.6)',
      }}
    >
      {/* Ambient glow */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" />

      {/* Card */}
      <div
        className="relative z-10 flex flex-col items-center gap-6 max-w-sm w-full mx-4 p-8 rounded-2xl text-center bg-zinc-950/90 border border-zinc-800 shadow-xl shadow-black/40 backdrop-blur-md"
      >
        {/* Animated server icon */}
        <div className="relative">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center bg-zinc-900 border border-zinc-800"
          >
            {recovering ? (
              // Checkmark when recovering
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            ) : (
              // Server icon when down
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
                <rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
                <line x1="6" y1="6" x2="6.01" y2="6"/>
                <line x1="6" y1="18" x2="6.01" y2="18"/>
              </svg>
            )}
          </div>
          {/* Pulse ring */}
          {!recovering && (
            <span
              className="absolute inset-0 rounded-2xl animate-ping opacity-20 bg-zinc-700"
            />
          )}
        </div>

        {/* Text */}
        {recovering ? (
          <>
            <div>
              <h2 className="text-xl font-bold text-zinc-100">Server is Back!</h2>
              <p className="text-sm mt-1.5 font-mono text-zinc-400">
                Resuming your session…
              </p>
            </div>
          </>
        ) : (
          <>
            <div>
              <h2 className="text-xl font-bold text-zinc-100">
                Server is Restarting{dots}
              </h2>
              <p className="text-sm mt-2 font-mono leading-relaxed text-zinc-400">
                The Revora backend is waking up from sleep mode. Your work is safe — please wait a moment.
              </p>
            </div>

            {/* Status pills */}
            <div className="flex gap-2 flex-wrap justify-center">
              {['Backend', 'Database', 'AI Engine'].map((service, i) => (
                <div
                  key={service}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-medium bg-zinc-900 border border-zinc-800 text-zinc-400"
                  style={{
                    animationDelay: `${i * 0.3}s`,
                  }}
                >
                  <span
                    className="w-1.5 h-1.5 rounded-full animate-pulse bg-zinc-400"
                  />
                  {service}
                </div>
              ))}
            </div>

            {/* Info note */}
            <p className="text-xs font-mono text-zinc-500">
              Free-tier services pause after 15 min of inactivity. Auto-recovering every 3s.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
