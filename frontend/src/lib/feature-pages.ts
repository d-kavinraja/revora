/**
 * Feature-flag to dashboard-page routing.
 *
 * A feature message belongs on the page for its own feature only. Keep the
 * more specific prefixes before their parents (`/model-lab/mouthmap` before
 * `/model-lab`) so the first match always wins.
 *
 * Keep this list in sync with FEATURE_META when a new feature page is added.
 */
export interface FeaturePageRoute {
  prefix: string;
  /** Feature keys whose enabled-state messages can appear on this route. */
  features: readonly string[];
  /**
   * Full-page feature that controls whether the page itself is available.
   * When this flag is not `enabled`, the page renders its existing
   * unavailable state and no informational banner is shown above it.
   */
  gateFeature?: string;
}

export const FEATURE_PAGE_ROUTES: readonly FeaturePageRoute[] = [
  {
    prefix: '/settings/analytics',
    features: ['analytics'],
    gateFeature: 'analytics',
  },
  {
    prefix: '/settings/usage',
    features: ['usage'],
    gateFeature: 'usage',
  },
  {
    prefix: '/settings/api-keys',
    features: ['api_keys_add'],
  },
  {
    prefix: '/settings/routing',
    features: ['routing_mapping'],
  },
  {
    prefix: '/model-lab/mouthmap',
    features: ['mouthmap'],
    gateFeature: 'mouthmap',
  },
  {
    prefix: '/model-lab/botaniq',
    features: ['botaniq'],
    gateFeature: 'botaniq',
  },
  {
    prefix: '/model-lab',
    features: ['model_lab'],
    gateFeature: 'model_lab',
  },
  {
    prefix: '/reviews',
    features: ['reviews', 'review_initiation'],
    gateFeature: 'reviews',
  },
  {
    prefix: '/guide',
    features: ['guide'],
    gateFeature: 'guide',
  },
] as const;

function normalizePathname(pathname: string): string {
  if (pathname.length <= 1) return pathname || '/';
  return pathname.replace(/\/+$/, '');
}

/** Resolve the most-specific feature route for a dashboard pathname. */
export function matchFeaturePage(
  pathname: string | null | undefined,
): FeaturePageRoute | null {
  if (!pathname) return null;

  const normalized = normalizePathname(pathname);
  return (
    FEATURE_PAGE_ROUTES.find(
      ({ prefix }) =>
        normalized === prefix || normalized.startsWith(`${prefix}/`),
    ) ?? null
  );
}
