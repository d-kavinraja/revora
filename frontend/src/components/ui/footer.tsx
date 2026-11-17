'use client';

import React, { useEffect, useId, useRef, useState, type FC, type ReactNode } from 'react';
import { CheckCircle2, TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
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
  /** The title for the newsletter subscription section. */
  newsletterTitle?: string;
  /** One-line description shown under the newsletter title. */
  newsletterDescription?: string;
  /** Async function to handle email subscription. Should return `true` for success and `false` for failure. */
  onSubscribe?: (email: string) => Promise<boolean>;
}

/**
 * A responsive and theme-adaptive footer component with a newsletter subscription form.
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
  newsletterTitle = 'Subscribe to our newsletter',
  newsletterDescription = 'Release notes and repository-aware review tips. One email a month.',
  onSubscribe = async (email) => {
    // Default mock implementation
    console.log(`Subscribing ${email}...`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
    return Math.random() > 0.3;
  },
  className,
  ...props
}) => {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [subscriptionStatus, setSubscriptionStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const errorId = useId();
  const statusId = useId();
  const resetTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (resetTimer.current) window.clearTimeout(resetTimer.current);
    },
    [],
  );

  const handleSubscribe = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmitting) return;

    const value = email.trim();
    if (!value) {
      setFieldError('Enter your email address.');
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      setFieldError('Enter a valid email address.');
      return;
    }

    setFieldError(null);
    setIsSubmitting(true);

    let success = false;
    try {
      success = onSubscribe ? await onSubscribe(value) : false;
    } catch {
      success = false;
    }

    setSubscriptionStatus(success ? 'success' : 'error');
    setIsSubmitting(false);
    if (success) setEmail('');

    if (resetTimer.current) window.clearTimeout(resetTimer.current);
    resetTimer.current = window.setTimeout(
      () => setSubscriptionStatus('idle'),
      success ? 4000 : 3000,
    );
  };

  const locked = isSubmitting || subscriptionStatus === 'success';

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
      <div className="container mx-auto grid grid-cols-1 gap-8 px-6 pt-6 pb-10 md:grid-cols-2 lg:grid-cols-4 lg:gap-10">
        {/* Company Info */}
        <div className="flex flex-col items-start gap-4">
          <div className="flex items-center gap-3">
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

        {/* Newsletter */}
        <div>
          <h3 className="mb-2 text-base font-semibold">{newsletterTitle}</h3>
          <p className="mb-4 max-w-sm text-sm leading-relaxed text-muted-foreground">
            {newsletterDescription}
          </p>
          <form onSubmit={handleSubscribe} noValidate className="relative w-full max-w-sm">
            <div className="relative flex rounded-md">
              <Input
                type="email"
                inputMode="email"
                autoComplete="email"
                placeholder="Your email address"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (fieldError) setFieldError(null);
                }}
                disabled={locked}
                aria-label="Email for newsletter"
                aria-invalid={Boolean(fieldError)}
                aria-describedby={fieldError ? errorId : undefined}
                className="pr-28 h-11 aria-invalid:border-destructive aria-invalid:ring-destructive/20"
              />
              <Button
                type="submit"
                disabled={locked}
                className="absolute right-0 top-0 h-full rounded-l-none px-5"
              >
                {isSubmitting
                  ? 'Subscribing...'
                  : subscriptionStatus === 'success'
                    ? 'Subscribed'
                    : 'Subscribe'}
              </Button>
            </div>
            <div className="mt-2 min-h-5 text-xs">
              {fieldError ? (
                <p id={errorId} role="alert" className="flex items-center gap-1.5 text-destructive">
                  <TriangleAlert size={13} aria-hidden="true" />
                  {fieldError}
                </p>
              ) : subscriptionStatus === 'success' ? (
                <p
                  id={statusId}
                  role="status"
                  className="flex items-center gap-1.5 text-success motion-reduce:animate-none"
                >
                  <CheckCircle2 size={13} aria-hidden="true" />
                  Subscribed. Check your inbox.
                </p>
              ) : subscriptionStatus === 'error' ? (
                <p
                  id={statusId}
                  role="alert"
                  className="flex items-center gap-1.5 text-destructive motion-reduce:animate-none"
                >
                  <TriangleAlert size={13} aria-hidden="true" />
                  Couldn&apos;t subscribe. Try again.
                </p>
              ) : null}
            </div>
          </form>
        </div>
      </div>

      {/* Bottom Copyright */}
      <div className="border-t border-border py-4 text-center text-sm text-muted-foreground">
        © {new Date().getFullYear()} {companyName}. All rights reserved.
      </div>
    </footer>
  );
};
