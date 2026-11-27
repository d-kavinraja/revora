'use client';

import Link from 'next/link';
import { REVORA } from '@/lib/site';

const LINKS = [
  { label: 'Setup', href: '#loop' },
  { label: 'Docs', href: REVORA.github.readme, external: true },
  { label: 'Model Lab', href: '/model-lab' },
  { label: 'Chat', href: '/chat' },
  { label: 'Sign in', href: '/login' },
] as const;

export function BloomNav() {
  return (
    <nav className="nav" aria-label="Primary">
      <Link href="/" aria-label="Revora home" className="brand">
        {/* eslint-disable-next-line @next/next/no-img-element -- brand asset served from /public; next/image adds no value at 24px */}
        <img src="/revora-logo.png" alt="" width={24} height={24} />
        Revora
      </Link>

      <div className="nav-links">
        {LINKS.map((link) =>
          'external' in link && link.external ? (
            <a
              key={link.label}
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="nav-link"
            >
              {link.label}
            </a>
          ) : (
            <Link key={link.label} href={link.href} className="nav-link">
              {link.label}
            </Link>
          ),
        )}
      </div>

      <a
        href={REVORA.github.app}
        target="_blank"
        rel="noopener noreferrer"
        className="btn nav-cta"
      >
        Install Revora-PR
      </a>
    </nav>
  );
}
