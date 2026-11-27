'use client';

import { useEffect, useState } from 'react';
import { Star } from 'lucide-react';

import { REVORA } from '@/lib/site';

const REPO_API = 'https://api.github.com/repos/d-kavinraja/revora';
const REPO_SLUG = REVORA.github.repo.replace('https://github.com/', '');

function GithubGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 .5C5.73.5.9 5.33.9 11.6c0 4.9 3.17 9.05 7.58 10.53.55.1.76-.24.76-.53v-1.87c-3.08.68-3.73-1.29-3.73-1.29-.51-1.29-1.24-1.63-1.24-1.63-1.01-.69.08-.68.08-.68 1.12.08 1.71 1.15 1.71 1.15 1 1.72 2.63 1.22 3.27.94.1-.73.39-1.24.71-1.52-2.46-.28-5.05-1.23-5.07-5.48 0-1.21.43-2.21 1.14-2.99-.11-.28-.49-1.41.11-2.94 0 0 .93-.3 3.05 1.15a10.5 10.5 0 0 1 5.55 0c2.12-1.45 3.05-1.15 3.05-1.15.6 1.53.22 2.66.11 2.94.71.78 1.14 1.78 1.14 2.99 0 4.26-2.6 5.19-5.07 5.47.4.35.76 1.03.76 2.08v3.09c0 .3.2.65.77.53A11.1 11.1 0 0 0 23.1 11.6C23.1 5.33 18.27.5 12 .5Z" />
    </svg>
  );
}

/** Compact display: 1,234 → 1.2k, 12,345 → 12k. */
function formatStars(count: number): string {
  if (count < 1000) return String(count);
  return `${(count / 1000).toFixed(count >= 10000 ? 0 : 1)}k`;
}

/**
 * Open-source pill in the hero's top-right corner. The star count is fetched
 * from the public GitHub REST API; rate limits, offline mode and malformed
 * responses all fall back to the plain "Star" label — never NaN/undefined.
 */
export function BloomGithubPill() {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    fetch(REPO_API, {
      signal: controller.signal,
      headers: { Accept: 'application/vnd.github+json' },
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((data: unknown) => {
        const count = (data as { stargazers_count?: unknown } | null)?.stargazers_count;
        if (typeof count === 'number' && Number.isFinite(count) && count >= 0) {
          setStars(count);
        }
      })
      .catch(() => {
        // Offline, aborted or rate-limited: keep the no-count fallback.
      });

    return () => controller.abort();
  }, []);

  return (
    <a
      className="github-pill"
      href={REVORA.github.repo}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={
        stars === null
          ? 'Star Revora on GitHub'
          : `Star Revora on GitHub, ${stars} stars`
      }
    >
      <span className="github-pill__icon">
        <GithubGlyph />
      </span>
      <span className="github-pill__slug">{REPO_SLUG}</span>
      <span className="github-pill__star" aria-hidden="true">
        <Star size={14} strokeWidth={2} />
      </span>
      <span className="github-pill__count">
        {stars === null ? 'Star' : formatStars(stars)}
      </span>
    </a>
  );
}
