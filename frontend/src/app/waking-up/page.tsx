'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import { useRouter, useSearchParams } from 'next/navigation';
import { checkHealth } from '@/lib/api';
import { isSafeInternalPath } from '@/lib/safe-redirect';
import MeadowRiseFooter from '@/components/ui/meadow-rise-footer';

const POLL_INTERVAL_MS = 3000;
const MAX_ATTEMPTS = 40; // ~2 minutes

type Status = 'waking' | 'alive' | 'timeout';

function WakingUpContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectParam = searchParams.get('redirect');
  // Never navigate to an attacker-supplied external URL after wake-up.
  const redirect = isSafeInternalPath(redirectParam) ? redirectParam : '/dashboard';
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<Status>('waking');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll the health endpoint
  useEffect(() => {
    // Immediately check once on mount
    checkHealth().then((alive) => {
      if (alive) {
        setStatus('alive');
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    });

    intervalRef.current = setInterval(async () => {
      setAttempt((a) => {
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

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  // Redirect once server is alive
  useEffect(() => {
    if (status === 'alive') {
      const t = setTimeout(() => router.replace(redirect), 1600);
      return () => clearTimeout(t);
    }
  }, [status, redirect, router]);

  // The headline: the maintenance notice, with the italic accent the scene
  // writes in by hand.
  const heading =
    status === 'alive'
      ? 'Revora is *awake again*\nback to the fields.'
      : 'Revora is in *planned maintenance*\nback in a moment.';

  // The supporting line carries the live status so the scene stays useful.
  const subheading =
    status === 'alive'
      ? 'All systems are back online. Taking you to where you left off…'
      : status === 'timeout'
        ? 'Maintenance is taking a little longer than expected. Give it a moment, then try again.'
        : `We're working on things and checking the service every ${POLL_INTERVAL_MS / 1000} seconds — attempt ${Math.min(attempt + 1, MAX_ATTEMPTS)} of ${MAX_ATTEMPTS}.`;

  // Only offer the pill when there is an action to take.
  const cta =
    status === 'timeout'
      ? { label: 'Try again', href: '/waking-up' }
      : status === 'waking'
        ? { label: 'Attempt ' + Math.min(attempt + 1, MAX_ATTEMPTS) + ' of ' + MAX_ATTEMPTS, href: '#' }
        : null;

  return (
    <main className="w-full">
      {/* On laptop/desktop the default scene headline (up to 92px) crowds the
          viewport edges; cap it so the notice sits centred with air around it.
          Mobile keeps the component's own scale. */}
      <style>{`
        @media (min-width: 900px) {
          .waking-meadow .mrf-h {
            font-size: clamp(40px, 4.4vw, 60px);
            max-width: 24ch;
          }
        }
      `}</style>
      <MeadowRiseFooter
        className="waking-meadow"
        name="Revora"
        brandHref="/"
        logo={
          // The real Revora mark, recoloured to a white silhouette so it reads
          // on the dark footer ground (brightness(0) kills the blue gradient,
          // invert(1) turns it pure white; transparency is preserved).
          <Image
            src="/revora-logo.png"
            alt=""
            width={30}
            height={30}
            priority
            className="mrf-mark"
            style={{ width: 30, height: 30, objectFit: 'contain', filter: 'brightness(0) invert(1)' }}
          />
        }
        tagline="The Open-Source AI Code Review Platform."
        heading={heading}
        subheading={subheading}
        cta={cta}
        preset="golden"
        seed={7}
        mist={0.6}
        newsletter={false}
        height="calc(100dvh - var(--revora-announcement-height, 0px))"
        heroHeight="clamp(500px, 74svh, 700px)"
        maxWidth="1080px"
        columns={[
          {
            title: 'Platform',
            links: [
              { label: 'Home', href: '/' },
              { label: 'Sign in', href: '/login' },
              { label: 'Create account', href: '/register' },
            ],
          },
          {
            title: 'Project',
            links: [
              { label: 'GitHub', href: 'https://github.com/d-kavinraja/revora' },
              { label: 'Releases', href: 'https://github.com/d-kavinraja/revora/releases' },
              { label: 'Contributing', href: 'https://github.com/d-kavinraja/revora/blob/main/CONTRIBUTING.md' },
            ],
          },
        ]}
        socials={[]}
        copyright={'© ' + new Date().getFullYear() + ' Revora. All rights reserved.'}
        legal={[{ label: 'License', href: 'https://github.com/d-kavinraja/revora/blob/main/LICENSE' }]}
      />
    </main>
  );
}

export default function WakingUpPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-[calc(100dvh-var(--revora-announcement-height,0px))] flex items-center justify-center bg-background">
          <div className="w-8 h-8 border-2 border-brand/30 border-t-brand rounded-full animate-spin" />
        </div>
      }
    >
      <WakingUpContent />
    </Suspense>
  );
}
