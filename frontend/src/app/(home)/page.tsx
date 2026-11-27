import { MaintenanceBanner } from '@/components/shared/maintenance-banner';
import { BloomLanding } from '@/components/home/bloom/bloom-landing';

/**
 * Cherry-blossom watercolor landing page (bloom design system).
 *
 * All copy, links and stats are Revora's real product facts; the visual
 * system, motion choreography and lifecycle are owned by `BloomLanding`.
 */
export default function LandingPage() {
  return (
    <>
      {/* Backend-health fallback (≤5s stale-cache window) — kept from the
          previous landing so outages are still surfaced. */}
      <MaintenanceBanner />
      <BloomLanding />
    </>
  );
}
