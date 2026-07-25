'use client';

import { useEffect, useState, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { checkHealth } from '@/lib/api';

const POLL_INTERVAL_MS = 10000; // Check every 10s during normal usage
const RECOVERY_INTERVAL_MS = 3000; // Check every 3s when server is down

// Pages where we should NOT show the overlay (login, waking-up, etc.)
const EXCLUDED_PATHS = ['/', '/login', '/register', '/waking-up', '/auth/callback'];

type ServerState = 'unknown' | 'alive' | 'down';

export function ServerStatusOverlay() {
  const pathname = usePathname();
  const [serverState, setServerState] = useState<ServerState>('unknown');
  const [dots, setDots] = useState('');
  const [recovering, setRecovering] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dotsRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
        if (serverState === 'down') {
          // Server just recovered — show "recovered" state briefly before hiding
          setRecovering(true);
          setTimeout(() => {
            setServerState('alive');
            setRecovering(false);
          }, 2000);
        } else {
          setServerState('alive');
        }
      } else {
        setServerState('down');
      }
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
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full opacity-15 blur-[100px]"
          style={{ background: 'radial-gradient(circle, #7c3aed 0%, transparent 70%)' }}
        />
      </div>

      {/* Card */}
      <div
        className="relative z-10 flex flex-col items-center gap-6 max-w-sm w-full mx-4 p-8 rounded-2xl text-center"
        style={{
          background: 'rgba(255,255,255,0.04)',
          border: '1px solid rgba(255,255,255,0.08)',
          boxShadow: '0 25px 50px rgba(0,0,0,0.5)',
        }}
      >
        {/* Animated server icon */}
        <div className="relative">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg, #7c3aed, #3b82f6)' }}
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
              className="absolute inset-0 rounded-2xl animate-ping opacity-25"
              style={{ background: 'linear-gradient(135deg, #7c3aed, #3b82f6)' }}
            />
          )}
        </div>

        {/* Text */}
        {recovering ? (
          <>
            <div>
              <h2 className="text-xl font-bold text-white">Server is Back!</h2>
              <p className="text-sm mt-1.5" style={{ color: 'rgba(255,255,255,0.5)' }}>
                Resuming your session…
              </p>
            </div>
          </>
        ) : (
          <>
            <div>
              <h2 className="text-xl font-bold text-white">
                Server is Restarting{dots}
              </h2>
              <p className="text-sm mt-2 leading-relaxed" style={{ color: 'rgba(255,255,255,0.55)' }}>
                The Revora backend is waking up from sleep mode. Your work is safe — please wait a moment.
              </p>
            </div>

            {/* Status pills */}
            <div className="flex gap-2 flex-wrap justify-center">
              {['Backend', 'Database', 'AI Engine'].map((service, i) => (
                <div
                  key={service}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium"
                  style={{
                    background: 'rgba(255,255,255,0.06)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    color: 'rgba(255,255,255,0.5)',
                    animationDelay: `${i * 0.3}s`,
                  }}
                >
                  <span
                    className="w-1.5 h-1.5 rounded-full animate-pulse"
                    style={{ background: '#eab308' }}
                  />
                  {service}
                </div>
              ))}
            </div>

            {/* Info note */}
            <p className="text-xs" style={{ color: 'rgba(255,255,255,0.3)' }}>
              Free-tier services pause after 15 min of inactivity. Auto-recovering every 3s.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
