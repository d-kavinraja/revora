import type { Metadata } from 'next';
import { REVORA, SOCIAL_IMAGE } from '@/lib/site';

const homeTitle = `${REVORA.systemName} | ${REVORA.tagline}`;
const homeDescription =
  'Repository-aware AI code review for GitHub pull requests. Revora reads your whole repository, then reports security, performance and code-quality findings.';

/**
 * The homepage replaces the inherited `openGraph`/`twitter` objects, so the generated
 * social artwork has to be referenced explicitly here (Next only falls back to the
 * `opengraph-image`/`twitter-image` conventions when the segment does not define its own
 * `images`). Both paths are the generated routes of those conventions.
 */
const openGraphImage = {
  url: SOCIAL_IMAGE.opengraphPath,
  width: SOCIAL_IMAGE.width,
  height: SOCIAL_IMAGE.height,
  alt: SOCIAL_IMAGE.alt,
};

const twitterImage = {
  url: SOCIAL_IMAGE.twitterPath,
  alt: SOCIAL_IMAGE.alt,
};

/**
 * Homepage metadata. This route group owns the canonical URL for `/`, so no other page
 * can be accidentally canonicalised to the homepage and the homepage never inherits a
 * different page's canonical.
 */
export const metadata: Metadata = {
  title: { absolute: homeTitle },
  description: homeDescription,
  alternates: { canonical: '/' },
  openGraph: {
    type: 'website',
    url: '/',
    siteName: REVORA.systemName,
    title: homeTitle,
    description: homeDescription,
    locale: 'en_US',
    images: [openGraphImage],
  },
  twitter: {
    card: 'summary_large_image',
    title: homeTitle,
    description: homeDescription,
    images: [twitterImage],
  },
};

export default function HomeLayout({ children }: { children: React.ReactNode }) {
  return children;
}
