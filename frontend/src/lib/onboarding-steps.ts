import { REVORA } from '@/lib/site';

export interface OnboardingStep {
  id: string;
  title: string;
  description: string;
  /** Short bullet list of sub-instructions. */
  bullets?: string[];
  /** Optional call-to-action. */
  cta?: {
    label: string;
    href: string;
    external?: boolean;
    variant?: 'primary' | 'secondary';
  };
  /** Optional secondary CTA. */
  secondaryCta?: {
    label: string;
    href: string;
    external?: boolean;
  };
}

/**
 * Single source of truth for the Revora onboarding tour and the Setup Guide
 * page. Both surfaces render from this list so content never drifts.
 */
export const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    id: 'install',
    title: 'Install the Revora GitHub App',
    description:
      'Revora needs the Revora GitHub App installed on your account before it can ' +
      'read your repositories and review pull requests. Installation is managed ' +
      'entirely by GitHub.',
    bullets: [
      'Click "Install Revora on GitHub" below.',
      'Choose the account or organization where your repositories live.',
      'GitHub will ask which repositories Revora may access.',
      'Return to Revora once installation is complete.',
    ],
    cta: {
      label: 'Install Revora on GitHub',
      href: REVORA.github.app,
      external: true,
      variant: 'primary',
    },
  },
  {
    id: 'access',
    title: 'Grant repository access',
    description:
      'Repository permissions are managed through the GitHub App installation ' +
      'settings — not inside Revora. You can grant access to all repositories or ' +
      'only the ones you want reviewed.',
    bullets: [
      'Open GitHub and go to Settings.',
      'Open Applications, then Installed GitHub Apps.',
      'Find Revora and click Configure.',
      'Under Repository access, select the repositories Revora should review.',
      'Save your changes if GitHub asks you to confirm.',
      'To add more repositories later, repeat these steps and add them to the list.',
    ],
  },
  {
    id: 'sync',
    title: 'Sync repositories into Revora',
    description:
      'After granting access, return to Revora and synchronize so the newly ' +
      'accessible repositories appear in your workspace.',
    bullets: [
      'Open the Repositories page in Revora.',
      'Click "Sync from GitHub".',
      'Wait for synchronization to finish.',
      'Verify that your repositories now appear in the list.',
    ],
    cta: {
      label: 'Open Repositories',
      href: '/repositories',
      variant: 'primary',
    },
  },
  {
    id: 'review',
    title: 'Start reviewing pull requests',
    description:
      'Once a repository is connected, configure it and open a pull request. ' +
      'Revora will detect the PR and run an automated review.',
    bullets: [
      'On the Repositories page, open a repository and configure its review model.',
      'Enable reviews for the repository.',
      'Open or create a pull request on GitHub.',
      'Revora will automatically review the pull request.',
      'View the review results on the Reviews page.',
    ],
    cta: {
      label: 'Open Reviews',
      href: '/reviews',
      variant: 'secondary',
    },
    secondaryCta: {
      label: 'Open Repositories',
      href: '/repositories',
    },
  },
];