'use client';

import React, { type FC, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import SplitFlapText from '@/components/ui/SplitFlapText';
import { REVORA } from '@/lib/site';

const GithubIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .5C5.73.5.9 5.33.9 11.6c0 4.9 3.17 9.05 7.58 10.53.55.1.76-.24.76-.53v-1.87c-3.08.68-3.73-1.29-3.73-1.29-.51-1.29-1.24-1.63-1.24-1.63-1.01-.69.08-.68.08-.68 1.12.08 1.71 1.15 1.71 1.15 1 1.72 2.63 1.22 3.27.94.1-.73.39-1.24.71-1.52-2.46-.28-5.05-1.23-5.05-5.48 0-1.21.43-2.21 1.14-2.99-.11-.28-.49-1.41.11-2.94 0 0 .93-.3 3.05 1.15a10.5 10.5 0 0 1 5.55 0c2.12-1.45 3.05-1.15 3.05-1.15.6 1.53.22 2.66.11 2.94.71.78 1.14 1.78 1.14 2.99 0 4.26-2.6 5.19-5.07 5.47.4.35.76 1.03.76 2.08v3.09c0 .3.2.65.77.53A11.1 11.1 0 0 0 23.1 11.6C23.1 5.33 18.27.5 12 .5Z" /></svg>
);
const IssueIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 8v4" /><path d="M12 16h.01" /></svg>
);

/** Real external destinations open in a new tab; in-app links keep navigating in place. */
function externalLinkProps(href: string) {
  return /^https?:\/\//i.test(href)
    ? { target: '_blank' as const, rel: 'noopener noreferrer' }
    : {};
}

/**
 * Props for the Footer component.
 */
interface FooterProps extends React.HTMLAttributes<HTMLElement> {
  /** The source URL for the company logo. */
  logoSrc: string;
  /** The name of the company, displayed next to the logo. */
  companyName?: string;
  /** A short description of the company. */
  description?: string;
  /** An array of objects for generating useful links. */
  usefulLinks?: { label: string; href: string }[];
  /** An array of objects for generating social media links. */
  socialLinks?: { label: string; href: string; icon: ReactNode }[];
}

/**
 * A responsive and theme-adaptive footer with branding, navigation and
 * product links.
 */
export const Footer: FC<FooterProps> = ({
  logoSrc,
  companyName = 'Revora',
  description = 'Revora is an open-source, repository-aware AI code review platform for GitHub pull requests.',
  usefulLinks = [
    { label: 'Documentation', href: REVORA.github.readme },
    { label: 'Install GitHub App', href: REVORA.github.app },
    { label: 'License', href: REVORA.github.license },
  ],
  socialLinks = [
    { label: 'GitHub Repository', href: REVORA.github.repo, icon: <GithubIcon /> },
    { label: 'Report an Issue', href: REVORA.github.issues, icon: <IssueIcon /> },
  ],
  className,
  ...props
}) => {
  return (
    <footer className={cn('bg-muted/50 text-foreground border-t border-border mt-auto', className)} {...props}>
      <p className="sr-only">
        Repository-aware. Machine-verified. AI code review.
      </p>
      <div className="split-flap-board" aria-hidden="true">
        <SplitFlapText
          words={['REPOSITORY AWARE', 'MACHINE VERIFIED', 'AI CODE REVIEW']}
          loop
          cycleDelay={2600}
          flipDuration={0.12}
          stagger={0.05}
          fontSize={30}
          gap={5}
          padTo={16}
          tileColor="var(--board-tile)"
          textColor="var(--board-text)"
        />
      </div>
      <div className="container mx-auto grid grid-cols-1 gap-8 px-6 pt-6 pb-10 md:grid-cols-2 lg:grid-cols-3 lg:gap-10">
        {/* Company Info */}
        <div className="flex flex-col items-start gap-4">
          <div className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element -- logoSrc is a runtime prop that may point at any host */}
            <img src={logoSrc} alt={`${companyName} Logo`} className="h-10 w-10 rounded-xl object-cover bg-background" />
            <span className="text-xl font-bold text-foreground">{companyName}</span>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
        </div>

        {/* Useful Links */}
        <div className="md:justify-self-center">
          <h3 className="mb-4 text-base font-semibold">Useful Links</h3>
          <ul className="space-y-3">
            {usefulLinks.map((link) => (
              <li key={link.label}>
                <a
                  href={link.href}
                  {...externalLinkProps(link.href)}
                  className="inline-flex min-h-11 items-center text-sm text-muted-foreground transition-colors hover:text-primary"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </div>

        {/* GitHub */}
        <div className="md:justify-self-center">
          <h3 className="mb-4 text-base font-semibold">GitHub</h3>
          <ul className="space-y-3">
            {socialLinks.map((link) => (
              <li key={link.label}>
                <a
                  href={link.href}
                  {...externalLinkProps(link.href)}
                  aria-label={link.label}
                  className="flex min-h-11 items-center gap-3 text-sm text-muted-foreground transition-colors hover:text-primary group"
                >
                  <span className="group-hover:scale-110 transition-transform">{link.icon}</span>
                  <span>{link.label}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Bottom Copyright */}
      <div className="border-t border-border py-4 text-center text-sm text-muted-foreground">
        © {new Date().getFullYear()} {companyName}. All rights reserved.
      </div>
    </footer>
  );
};
