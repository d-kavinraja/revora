'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, ExternalLink } from 'lucide-react';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import DepthCarousel, {
  type DepthCarouselSlide,
} from '@/components/ui/depth-carousel';
import { usePlatformFeatures, featureState } from '@/lib/use-platform-features';
import { REVORA } from '@/lib/site';
import { useThemeStore } from '@/store/useThemeStore';

interface GuideCta {
  label: string;
  href: string;
  external?: boolean;
}

interface GuideStep {
  id: string;
  title: string;
  description: string;
  bullets: string[];
  cta: GuideCta;
  secondaryCta?: GuideCta;
}

/**
 * The onboarding steps rendered as 3D carousel cards. The copy mirrors the
 * onboarding tour so the guide and the tour never drift apart.
 */
const GUIDE_STEPS: GuideStep[] = [
  {
    id: 'install',
    title: 'Install the Revora GitHub App',
    description:
      'Revora reads repositories through its GitHub App. Installation is managed by GitHub, so you always know exactly which repositories are in scope.',
    bullets: [
      'Open the Revora GitHub App installation page.',
      'Choose the account or organization that owns your repositories.',
      'Select the repositories Revora is allowed to read.',
      'Return to Revora and confirm the connection.',
    ],
    cta: {
      label: 'Install Revora on GitHub',
      href: REVORA.github.app,
      external: true,
    },
  },
  {
    id: 'access',
    title: 'Grant repository access',
    description:
      'Repository permissions are managed through the GitHub App installation ' +
      'settings — not inside Revora. You can grant access to all repositories ' +
      'or only the ones you want reviewed.',
    bullets: [
      'Open GitHub and go to Settings.',
      'Open Applications, then Installed GitHub Apps.',
      'Find Revora and click Configure.',
      'Under Repository access, select the repositories Revora should review.',
      'Save your changes if GitHub asks you to confirm.',
      'To add more repositories later, repeat these steps and add them to the list.',
    ],
    cta: {
      label: 'Open GitHub App Settings',
      href: 'https://github.com/settings/installations',
      external: true,
    },
  },
  {
    id: 'providers',
    title: 'Configure API keys & providers',
    description:
      'Pick the engine that powers your reviews. Revora never substitutes a model silently — whatever you configure is what actually runs.',
    bullets: [
      'Open Settings → Providers and choose your review engine.',
      'Add an API key for your provider, or use kLLM — kLLM is managed by Revora and needs no API key.',
      'Revora validates the key and lists the models it can reach.',
      'Choose a default review model for new repositories.',
    ],
    cta: {
      label: 'Open Providers',
      href: '/settings/providers',
    },
  },
  {
    id: 'repositories',
    title: 'Connect & map repositories',
    description:
      'Sync the repositories the GitHub App can see, then map each one to the provider and model that should review its pull requests.',
    bullets: [
      'Open Repositories and run “Sync from GitHub”.',
      'Choose which synced repositories Revora should review.',
      'Map a provider and review model per repository.',
      'Confirm the mapping shows the provider you expect.',
    ],
    cta: {
      label: 'Open Repositories',
      href: '/repositories',
    },
  },
  {
    id: 'reviews',
    title: 'Start reviewing pull requests',
    description:
      'With a repository mapped, Revora reviews every new pull request on its own — no manual trigger, no reviewer seat required.',
    bullets: [
      'Open a pull request in one of your connected repositories.',
      'Revora detects the PR and queues an automated review.',
      'Read the inline review comments and the final summary.',
      'Track every execution from the Reviews page.',
    ],
    cta: {
      label: 'Open Reviews',
      href: '/reviews',
    },
    secondaryCta: {
      label: 'Open Repositories',
      href: '/repositories',
    },
  },
];

const GUIDE_SLIDES: DepthCarouselSlide[] = GUIDE_STEPS.map((step) => ({
  alt: step.title,
}));

type GuideBreakpoint = 'mobile' | 'tablet' | 'desktop';

interface GuideCarouselMetrics {
  cardWidth: number;
  cardHeight: number;
  radius: number;
  depth: number;
  spread: number;
  tilt: number;
  visibleCards: number;
  scaleMode: 'stack' | 'card';
}

const CAROUSEL_METRICS: Record<GuideBreakpoint, GuideCarouselMetrics> = {
  mobile: {
    cardWidth: 300,
    cardHeight: 440,
    radius: 16,
    depth: 150,
    spread: 44,
    tilt: 14,
    visibleCards: 2,
    scaleMode: 'card',
  },
  tablet: {
    cardWidth: 420,
    cardHeight: 460,
    radius: 18,
    depth: 190,
    spread: 70,
    tilt: 18,
    visibleCards: 3,
    scaleMode: 'stack',
  },
  desktop: {
    cardWidth: 500,
    cardHeight: 460,
    radius: 20,
    depth: 220,
    spread: 90,
    tilt: 22,
    visibleCards: 3,
    scaleMode: 'stack',
  },
};

/** Viewport-aware carousel sizing so every card stays readable and unclipped. */
function useGuideBreakpoint(): GuideBreakpoint {
  const [breakpoint, setBreakpoint] = useState<GuideBreakpoint>('desktop');

  useEffect(() => {
    const update = () => {
      const width = window.innerWidth;
      setBreakpoint(
        width < 640 ? 'mobile' : width < 1024 ? 'tablet' : 'desktop',
      );
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  return breakpoint;
}

function CtaLink({
  cta,
  variant = 'primary',
  compact = false,
}: {
  cta: GuideCta;
  variant?: 'primary' | 'secondary';
  compact?: boolean;
}) {
  const className =
    variant === 'primary'
      ? [
          // Solid, saturated brand fill with a pure white label and a crisp
          // edge, so the primary action stays legible in both themes.
          'inline-flex items-center justify-center gap-1.5 rounded-lg',
          'border border-[#4338ca] bg-[#4f46e5] font-medium text-white',
          'shadow-[inset_0_1px_0_rgba(255,255,255,0.22),0_10px_24px_-12px_rgba(79,70,229,0.95)]',
          'transition-[background-color,border-color,box-shadow] duration-150',
          'hover:border-[#3730a3] hover:bg-[#4338ca]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a5b4fc]',
          'focus-visible:ring-offset-2 focus-visible:ring-offset-transparent',
          compact
            ? 'min-h-8 px-2.5 py-1 text-[11px]'
            : 'min-h-9 px-3 py-1.5 text-xs',
        ].join(' ')
      : [
          'inline-flex items-center justify-center gap-1.5 rounded-lg',
          'border border-border bg-surface-2 font-medium text-foreground',
          'transition-colors duration-150 hover:border-brand/50 hover:bg-surface-3',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a5b4fc]',
          'focus-visible:ring-offset-2 focus-visible:ring-offset-transparent',
          compact
            ? 'min-h-8 px-2.5 py-1 text-[11px]'
            : 'min-h-9 px-3 py-1.5 text-xs',
        ].join(' ');

  if (cta.external) {
    return (
      <a
        href={cta.href}
        target="_blank"
        rel="noopener noreferrer"
        className={className}
      >
        {cta.label}
        <ExternalLink size={12} aria-hidden="true" />
      </a>
    );
  }

  return (
    <Link href={cta.href} className={className}>
      {cta.label}
    </Link>
  );
}

export default function SetupGuidePage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'guide');
  const { theme } = useThemeStore();
  const breakpoint = useGuideBreakpoint();
  const [activeStep, setActiveStep] = useState(0);

  if (status !== 'enabled') {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <FeatureUnavailable status={status} message={message} title="Setup Guide is unavailable" variant="page" />
      </div>
    );
  }

  const metrics = CAROUSEL_METRICS[breakpoint];
  const isLight = theme === 'light';
  // Dark mode keeps a brighter, slower ramp so receding cards stay separated
  // from the dotted canvas instead of collapsing into pure black.
  const tint = isLight ? '#c9cee6' : '#39415a';
  const falloff = isLight ? 0.16 : 0.1;
  const compact = breakpoint === 'mobile';

  const renderCard = (_item: DepthCarouselSlide, index: number) => {
    const step = GUIDE_STEPS[index];
    if (!step) return null;

    return (
      <div
        className={`flex h-full w-full flex-col text-left ${
          compact ? 'gap-2.5 p-4' : 'gap-3.5 p-5 sm:p-6'
        }`}
      >
        <div className="flex items-start gap-3">
          <span
            className={`flex shrink-0 items-center justify-center rounded-full bg-brand/10 font-bold text-brand ${
              compact ? 'h-7 w-7 text-xs' : 'h-9 w-9 text-sm'
            }`}
          >
            {index + 1}
          </span>
          <h3
            className={`font-semibold leading-snug text-foreground ${
              compact ? 'text-sm' : 'text-base sm:text-lg'
            }`}
          >
            {step.title}
          </h3>
        </div>

        <p
          className={`text-muted-foreground ${
            compact
              ? 'text-[11px] leading-snug'
              : 'text-xs leading-relaxed sm:text-sm'
          }`}
        >
          {step.description}
        </p>

        <ul
          className={`flex-1 text-foreground/85 ${
            compact
              ? 'space-y-1.5 text-[11px] leading-snug'
              : 'space-y-2 text-xs leading-relaxed sm:text-sm'
          }`}
        >
          {step.bullets.map((bullet) => (
            <li key={bullet} className="flex items-start gap-2">
              <CheckCircle2
                size={compact ? 12 : 14}
                className="mt-0.5 shrink-0 text-brand"
                aria-hidden="true"
              />
              <span>{bullet}</span>
            </li>
          ))}
        </ul>

        {/* Stop pointer events from reaching the carousel so the buttons are
            never swallowed by a drag gesture. */}
        <div
          className="flex flex-wrap items-center gap-2 pt-0.5"
          onPointerDown={(event) => event.stopPropagation()}
        >
          <CtaLink cta={step.cta} compact={compact} />
          {step.secondaryCta && (
            <CtaLink cta={step.secondaryCta} variant="secondary" compact={compact} />
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="w-full min-h-[calc(100dvh-var(--revora-announcement-height,0px))] pb-16">
      <div className="mx-auto w-full max-w-6xl px-6 pt-6">
        <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-heading font-bold tracking-tight text-foreground md:text-3xl">
              Setup guide
            </h1>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Connect your GitHub repositories, configure your AI review
              provider, and automate pull request reviews in {GUIDE_STEPS.length}{' '}
              steps.
            </p>
          </div>

          <span className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-full border border-border bg-surface-1/80 px-3 py-1 text-xs font-medium text-foreground backdrop-blur">
            Step {activeStep + 1} of {GUIDE_STEPS.length}
          </span>
        </header>

        {/* Transparent stage: the cards float over the page's dotted canvas. */}
        <section className="mt-6" aria-label="Setup steps carousel">
          <div className="relative h-[500px] w-full sm:h-[520px] lg:h-[560px]">
            <DepthCarousel
              items={GUIDE_SLIDES}
              renderCard={renderCard}
              index={activeStep}
              onChange={(nextIndex) => setActiveStep(nextIndex)}
              cardWidth={metrics.cardWidth}
              cardHeight={metrics.cardHeight}
              radius={metrics.radius}
              depth={metrics.depth}
              spread={metrics.spread}
              tilt={metrics.tilt}
              tiltDirection="right"
              perspective={1400}
              visibleCards={metrics.visibleCards}
              scaleMode={metrics.scaleMode}
              falloff={falloff}
              blur={6}
              duration={700}
              ease="power3.out"
              loop={false}
              showControls
              showIndicators
              tint={tint}
              ariaLabel="Setup guide steps"
            />
          </div>
        </section>
      </div>
    </div>
  );
}
