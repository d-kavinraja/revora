/**
 * Single source of truth for Revora's public identity, canonical origin and the
 * real external destinations that are referenced from metadata and the footer.
 *
 * Nothing in here is secret: these are public, verifiable facts about the project.
 */
export const REVORA = {
  /** Brand name. */
  name: 'Revora',
  /** Full product identity (used for titles, OpenGraph and structured data). */
  systemName: 'Revora System',
  /** The shipped GitHub App. */
  appName: 'Revora-PR',
  /** One-line description of what the product actually is. */
  tagline: 'Repository-Aware AI Code Review',
  description:
    'Open-source, repository-aware AI code review for GitHub pull requests. Revora reads the whole repository before it reviews a change.',
  /** Real, existing destinations only - never invent profiles or pages. */
  github: {
    repo: 'https://github.com/d-kavinraja/revora',
    app: 'https://github.com/apps/revora-pr',
    issues: 'https://github.com/d-kavinraja/revora/issues',
    license: 'https://github.com/d-kavinraja/revora/blob/main/LICENSE',
    readme: 'https://github.com/d-kavinraja/revora#readme',
  },
} as const;

/** Local development fallback when no deployment origin can be detected. */
const LOCAL_SITE_URL = 'http://localhost:3000';

/**
 * Contract for the generated social preview artwork. Kept free of any `next/og`
 * import so plain Server Components can reference it without pulling the image
 * renderer into their module graph.
 */
export const SOCIAL_IMAGE = {
  width: 1200,
  height: 630,
  alt: 'Revora System - repository-aware AI code review for GitHub pull requests',
  /** Routes produced by the `app/opengraph-image.tsx` / `app/twitter-image.tsx` conventions. */
  opengraphPath: '/opengraph-image',
  twitterPath: '/twitter-image',
} as const;

function normalizeOrigin(origin: string): string {
  const withProtocol = /^https?:\/\//i.test(origin) ? origin : `https://${origin}`;
  return withProtocol.replace(/\/+$/, '');
}

/**
 * Resolve the canonical production origin.
 *
 * 1. `NEXT_PUBLIC_SITE_URL` - explicit override (any host, including a custom domain).
 * 2. `VERCEL_PROJECT_PRODUCTION_URL` - Vercel's *stable production* domain. It is
 *    available on production and preview deployments alike, which is exactly why it is
 *    used here: a preview deployment must never become the canonical identity.
 * 3. `VERCEL_URL` - the current deployment URL (last-resort fallback off-Vercel).
 * 4. `http://localhost:3000` - local development.
 */
export function getSiteUrl(): string {
  const candidates = [
    process.env.NEXT_PUBLIC_SITE_URL,
    process.env.VERCEL_PROJECT_PRODUCTION_URL,
    process.env.VERCEL_URL,
  ].find((value) => typeof value === 'string' && value.trim().length > 0);

  return candidates ? normalizeOrigin(candidates.trim()) : LOCAL_SITE_URL;
}

/**
 * Production deployments are indexable; Vercel preview deployments are not, so that
 * previews can never compete with - or be mistaken for - the production site.
 */
export function isIndexableDeployment(): boolean {
  const vercelEnv = process.env.VERCEL_ENV?.trim();
  return !vercelEnv || vercelEnv === 'production';
}

/** Bare host (no protocol) used for display inside the generated social image. */
export function getSiteHost(): string {
  return getSiteUrl().replace(/^https?:\/\//i, '');
}
