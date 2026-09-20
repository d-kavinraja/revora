import { REVORA, getSiteUrl } from './site';

/**
 * Capabilities that are actually shipped and documented in the repository
 * (README feature status + PRODUCT.md). No roadmap items, no marketing claims.
 */
const APPLICATION_FEATURES = [
  'Repository-aware AI code review of GitHub pull requests',
  'Repository intelligence engine with a zero-LLM detector suite',
  'Security and secret detection before merge',
  'Performance and code-quality analysis',
  'Machine-verified findings (file/line existence and hallucination checks)',
  'Bring your own key (BYOK) multi-provider LLM routing',
  'Self-hostable, MIT-licensed open-source deployment',
];

/**
 * Truthful JSON-LD entity graph:
 *
 *   Revora (Organization) -> Revora System (SoftwareApplication, WebSite) -> GitHub -> official site
 *
 * Only verifiable facts are published. There are deliberately no ratings, reviews,
 * testimonials, user counts, funding, awards or social profiles, because none exist.
 */
export function buildStructuredData() {
  const siteUrl = getSiteUrl();
  const organizationId = `${siteUrl}/#organization`;
  const websiteId = `${siteUrl}/#website`;
  const softwareId = `${siteUrl}/#software`;

  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'Organization',
        '@id': organizationId,
        name: REVORA.name,
        alternateName: REVORA.systemName,
        url: `${siteUrl}/`,
        description:
          'Open-source project building repository-aware AI code review tooling for GitHub pull requests.',
        logo: {
          '@type': 'ImageObject',
          url: `${siteUrl}/revora-logo.png`,
          width: 523,
          height: 477,
        },
        sameAs: [REVORA.github.repo],
      },
      {
        '@type': 'WebSite',
        '@id': websiteId,
        url: `${siteUrl}/`,
        name: REVORA.name,
        alternateName: REVORA.systemName,
        description: REVORA.description,
        inLanguage: 'en',
        publisher: { '@id': organizationId },
      },
      {
        '@type': 'SoftwareApplication',
        '@id': softwareId,
        name: REVORA.systemName,
        alternateName: [REVORA.name, REVORA.appName],
        applicationCategory: 'DeveloperApplication',
        applicationSubCategory: 'AI code review',
        operatingSystem: 'Web',
        url: `${siteUrl}/`,
        description:
          'Revora System reviews GitHub pull requests with the whole repository in context, then verifies every finding against real code before it is reported.',
        isAccessibleForFree: true,
        license: REVORA.github.license,
        codeRepository: REVORA.github.repo,
        installUrl: REVORA.github.app,
        featureList: APPLICATION_FEATURES,
        publisher: { '@id': organizationId },
        isPartOf: { '@id': websiteId },
      },
    ],
  };
}
