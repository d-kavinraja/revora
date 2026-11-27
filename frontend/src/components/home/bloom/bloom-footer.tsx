'use client';

import Link from 'next/link';
import { REVORA } from '@/lib/site';

const GithubIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
    <path d="M12 .5C5.73.5.9 5.33.9 11.6c0 4.9 3.17 9.05 7.58 10.53.55.1.76-.24.76-.53v-1.87c-3.08.68-3.73-1.29-3.73-1.29-.51-1.29-1.24-1.63-1.24-1.63-1.01-.69.08-.68.08-.68 1.12.08 1.71 1.15 1.71 1.15 1 1.72 2.63 1.22 3.27.94.1-.73.39-1.24.71-1.52-2.46-.28-5.05-1.23-5.05-5.48 0-1.21.43-2.21 1.14-2.99-.11-.28-.49-1.41.11-2.94 0 0 .93-.3 3.05 1.15a10.5 10.5 0 0 1 5.55 0c2.12-1.45 3.05-1.15 3.05-1.15.6 1.53.22 2.66.11 2.94.71.78 1.14 1.78 1.14 2.99 0 4.26-2.6 5.19-5.07 5.47.4.35.76 1.03.76 2.08v3.09c0 .3.2.65.77.53A11.1 11.1 0 0 0 23.1 11.6C23.1 5.33 18.27.5 12 .5Z" />
  </svg>
);

const IssueIcon = () => (
  <svg
    viewBox="0 0 24 24"
    width="18"
    height="18"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8v4" />
    <path d="M12 16h.01" />
  </svg>
);

const FOOTER_LINKS = [
  { label: 'Toolkit', href: '/model-lab', external: false },
  { label: 'Docs', href: REVORA.github.readme, external: true },
  { label: 'Help', href: REVORA.github.issues, external: true },
  { label: 'License', href: REVORA.github.license, external: true },
] as const;

const SOCIALS = [
  { label: 'Revora on GitHub', href: REVORA.github.repo, icon: <GithubIcon /> },
  { label: 'Report an issue', href: REVORA.github.issues, icon: <IssueIcon /> },
] as const;

/**
 * Lime footer with the animated Revora emblem: three dots bounce, merge into
 * the ribbon "R" mark (drawn via stroke-dashoffset), then a ring draws around
 * it. The mark paths are traced from the brand's gradient "R" logo.
 */
export function BloomFooter() {
  return (
    <footer className="footer" id="footer">
      <Link href="/" aria-label="Revora" className="f-logo-link">
        <svg className="f-logo" viewBox="0 0 80 80" aria-hidden="true">
          <defs>
            <linearGradient id="revGrad" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0" stopColor="#22d3ee" />
              <stop offset="0.5" stopColor="#3b82f6" />
              <stop offset="1" stopColor="#8b5cf6" />
            </linearGradient>
          </defs>

          <circle
            id="fRing"
            cx="40"
            cy="40"
            r="37"
            fill="none"
            stroke="#111"
            strokeWidth="2.4"
            strokeDasharray="233"
            strokeDashoffset="233"
            transform="rotate(-90 40 40)"
          />

          <circle className="fdot" cx="22" cy="40" r="4.5" fill="#111" />
          <circle className="fdot" cx="40" cy="40" r="4.5" fill="#111" />
          <circle className="fdot" cx="58" cy="40" r="4.5" fill="#111" />

          {/* Ribbon "R" — upper loop + sweeping leg, drawn on scroll. */}
          <path
            id="fMarkA"
            d="M20 56 C8 40 14 14 34 13 C52 12 56 28 42 33 L30 36"
            pathLength={60}
            fill="none"
            stroke="url(#revGrad)"
            strokeWidth="9"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ strokeDasharray: 60, strokeDashoffset: 60 }}
          />
          <path
            id="fMarkB"
            d="M30 36 C40 39 40 46 54 58 C56 60 58 59 58 55"
            pathLength={60}
            fill="none"
            stroke="url(#revGrad)"
            strokeWidth="9"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ strokeDasharray: 60, strokeDashoffset: 60 }}
          />
        </svg>
      </Link>

      <nav className="f-links" aria-label="Footer">
        {FOOTER_LINKS.map((link) =>
          link.external ? (
            <a
              key={link.label}
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {link.label}
            </a>
          ) : (
            <Link key={link.label} href={link.href}>
              {link.label}
            </Link>
          ),
        )}
      </nav>

      <div className="f-social">
        {SOCIALS.map((social) => (
          <a
            key={social.label}
            href={social.href}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={social.label}
          >
            {social.icon}
          </a>
        ))}
      </div>

      <p className="f-copy">© 2026 Revora. All rights reserved.</p>
    </footer>
  );
}
