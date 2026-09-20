import type { MetadataRoute } from 'next';
import { getSiteUrl } from '@/lib/site';

/**
 * `/sitemap.xml`
 *
 * Only genuinely public, indexable pages are listed. Revora is a single public page
 * product: the landing page documents the product and links to the GitHub App and the
 * open-source repository, so nothing else qualifies today.
 *
 * Deliberately excluded (they are authentication-gated or transient and carry
 * `X-Robots-Tag: noindex` via `src/proxy.ts`):
 *   /dashboard, /repositories, /reviews/*, /settings/*, /profile, /guide,
 *   /login, /register, /auth/callback, /waking-up and every /api/ route.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const siteUrl = getSiteUrl();

  return [
    {
      url: `${siteUrl}/`,
      lastModified: new Date(),
      changeFrequency: 'weekly',
      priority: 1,
    },
  ];
}
