import type { MetadataRoute } from 'next';
import { getSiteUrl, isIndexableDeployment } from '@/lib/site';

/**
 * `/robots.txt`
 *
 * Production: the public site is crawlable and only the JSON API is kept out of the
 * index (API responses are not HTML pages, so a disallow cannot hide a noindex).
 *
 * Authenticated/app routes (`/dashboard`, `/repositories`, `/reviews`, `/settings`,
 * `/profile`, `/guide`), the auth flow (`/login`, `/register`, `/auth/callback`) and the
 * transient `/waking-up` status page are intentionally NOT disallowed here: disallowing
 * them would stop crawlers from ever reading their `X-Robots-Tag: noindex` directive
 * (see `src/proxy.ts`), which is the correct way to keep them out of search results.
 *
 * Preview deployments: the entire deployment is disallowed so a preview can never be
 * indexed alongside - or instead of - the production site.
 */
export default function robots(): MetadataRoute.Robots {
  const siteUrl = getSiteUrl();

  if (!isIndexableDeployment()) {
    return {
      rules: [{ userAgent: '*', disallow: '/' }],
    };
  }

  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: ['/api/'],
      },
    ],
    sitemap: `${siteUrl}/sitemap.xml`,
    host: siteUrl,
  };
}
