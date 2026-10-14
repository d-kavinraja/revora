'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { REVORA } from '@/lib/site';
import { ThemeToggle } from '@/components/ui/theme-toggle';
import { ModelLabCard } from './model-lab-card';
import './data-signal-hero.css';

const VIDEO_SRC =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260808_064556_051587f1-74a1-4336-8c05-4dde3594ed05.mp4';

const NAV = [
  { label: 'Product', href: '#setup' },
  { label: 'Docs', href: REVORA.github.readme },
  { label: 'Install', href: REVORA.github.app },
  { label: 'Sign In', href: '/login' },
];

export function DataSignalHero() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsible, setCollapsible] = useState(false);
  const [now, setNow] = useState<string | null>(null);
  const headerRef = useRef<HTMLElement>(null);
  const cardRef = useRef<HTMLElement>(null);
  const fallbackRef = useRef<number | null>(null);

  // Live timezone clock in "9:47 PM • 14 July 2026" format, client-only.
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
      const date = `${d.getDate()} ${d.toLocaleString('en-US', { month: 'long' })} ${d.getFullYear()}`;
      setNow(`${time} • ${date}`);
    };
    tick();
    const id = window.setInterval(tick, 20_000);
    return () => window.clearInterval(id);
  }, []);

  // One-shot entrance timeline gate: `motion-pending` + 3500ms fallback.
  useEffect(() => {
    const root = document.documentElement;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) return;
    root.classList.add('motion-pending');
    fallbackRef.current = window.setTimeout(() => {
      root.classList.remove('motion-pending');
    }, 3500);
    const card = cardRef.current;
    const release = () => {
      root.classList.remove('motion-pending');
      if (fallbackRef.current) window.clearTimeout(fallbackRef.current);
    };
    card?.addEventListener('animationend', release);
    return () => {
      root.classList.remove('motion-pending');
      if (fallbackRef.current) window.clearTimeout(fallbackRef.current);
      card?.removeEventListener('animationend', release);
    };
  }, []);

  // Track whether the hamburger menu is active (tablet/mobile).
  useEffect(() => {
    const mq = window.matchMedia(
      '(max-width: 619px), (min-width: 620px) and (max-width: 790px), (min-width: 620px) and (max-width: 1100px) and (orientation: portrait)',
    );
    const sync = () => {
      setCollapsible(mq.matches);
      if (!mq.matches) setMenuOpen(false);
    };
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);

  // Hamburger: Escape / outside pointer / link click closes; focus first link on open.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    const onPointer = (e: PointerEvent) => {
      if (headerRef.current && !headerRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    headerRef.current?.querySelector<HTMLAnchorElement>('.ds-nav a')?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [menuOpen]);

  return (
    <main className="ds-viewport">
      {/* Display + UI type: closest public analogues to the prompt's
          Reference Display / Reference Sans (fictional names). */}
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link
        href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@100..900&family=Source+Serif+4:opsz,wght@8..60,200..900&display=swap"
        rel="stylesheet"
      />
      <section className="ds-screen" id="screen">
        <video
          className="ds-background"
          autoPlay
          muted
          loop
          playsInline
          disablePictureInPicture
          aria-hidden="true"
        >
          <source src={VIDEO_SRC} type="video/mp4" />
        </video>

        <header ref={headerRef} className={cn('ds-header', menuOpen && 'menu-open')}>
          <div className="ds-entrance ds-entrance-brand">
            <Link href="/" aria-label="Revora home" className="ds-brand">
              <Image
                src="/revora-logo.png"
                alt=""
                width={25}
                height={25}
                className="ds-brand-logo"
                priority
              />
              <span className="ds-brand-name">Revora</span>
            </Link>
          </div>

          <div
            className="ds-header-actions"
            id="tablet-navigation"
            inert={!menuOpen && collapsible}
          >
            <nav aria-label="Primary" className="ds-nav">
              <span className="ds-entrance ds-entrance-nav" style={{ animationDelay: '130ms' }}>
                <Link href={NAV[0].href} onClick={() => setMenuOpen(false)} className="ds-nav-link ds-nav-link-active">
                  {NAV[0].label}
                </Link>
              </span>
              <span className="ds-entrance ds-entrance-nav" style={{ animationDelay: '175ms' }}>
                <Link href={NAV[1].href} onClick={() => setMenuOpen(false)} className="ds-nav-link">
                  {NAV[1].label}
                </Link>
              </span>
              <span className="ds-entrance ds-entrance-nav" style={{ animationDelay: '220ms' }}>
                <Link href={NAV[2].href} onClick={() => setMenuOpen(false)} className="ds-nav-link">
                  {NAV[2].label}
                </Link>
              </span>
              <span className="ds-entrance ds-entrance-nav ds-nav-fourth" style={{ animationDelay: '265ms' }}>
                <Link href={NAV[3].href} onClick={() => setMenuOpen(false)} className="ds-nav-link">
                  {NAV[3].label}
                </Link>
              </span>
            </nav>

            <div
              className="ds-entrance ds-entrance-nav ds-time-panel"
              style={{ animationDuration: '520ms', animationDelay: '180ms' }}
              role="status"
              aria-label="Local time"
            >
              <span className="ds-time-label">Timezone</span>
              <span className="ds-time-value">{now ?? ' '}</span>
            </div>

            <div className="ds-entrance ds-entrance-action ds-signup-wrap" style={{ animationDelay: '220ms' }}>
              <span className="ds-theme-wrap">
                <ThemeToggle />
              </span>
              <Link href="/register" className="ds-sign-up">
                Sign Up
              </Link>
            </div>
          </div>

          <div className="ds-entrance ds-entrance-action ds-toggle-wrap" style={{ animationDelay: '140ms' }}>
            <button
              type="button"
              className="ds-menu-toggle"
              aria-expanded={menuOpen}
              aria-controls="tablet-navigation"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              onClick={() => setMenuOpen((v) => !v)}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path
                  d={menuOpen ? 'M5 5l10 10M15 5L5 15' : 'M4 7h12M4 13h12'}
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        </header>

        <section className="ds-hero" aria-label="Revora introduction">
          <div className="ds-hero-content">
            <h1 className="ds-hero-title">
              <span className="ds-line ds-line-one">
                <span className="ds-line-reveal ds-line-reveal-one">Stop Reviewing</span>
              </span>
              <span className="ds-line ds-line-two">
                <span className="ds-line-reveal ds-line-reveal-two">Diffs Blind.</span>
              </span>
            </h1>
            <p className="ds-entrance ds-entrance-copy ds-hero-copy">
              Your repo is scattered across files.
              <br />
              Revora reads the whole repository, verifies every
              <br />
              finding, so every merge is backed by code you trust.
            </p>
            <div className="ds-entrance ds-entrance-action ds-cta-wrap">
              <a
                href={REVORA.github.app}
                target="_blank"
                rel="noopener noreferrer"
                className="ds-primary-cta"
              >
                <span className="ds-label">Install Revora-PR</span>
                <span aria-hidden="true" className="ds-arrow-box">
                  <ArrowRight size={14} strokeWidth={2.2} />
                </span>
              </a>
            </div>
          </div>

          <article ref={cardRef} aria-label="Model Lab feature" className="ds-demo-card">
            <ModelLabCard />
          </article>
        </section>
      </section>
    </main>
  );
}
