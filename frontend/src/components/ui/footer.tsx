'use client';

import React, { useState, type FC, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

const FacebookIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z" /></svg>
);
const InstagramIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="20" height="20" x="2" y="2" rx="5" ry="5" /><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" /><line x1="17.5" x2="17.51" y1="6.5" y2="6.5" /></svg>
);
const XIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>
);

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
  /** Async function to handle email subscription. Should return `true` for success and `false` for failure. */
  onSubscribe?: (email: string) => Promise<boolean>;
}

/**
 * A responsive and theme-adaptive footer component with a newsletter subscription form.
 */
export const Footer: FC<FooterProps> = ({
  logoSrc,
  companyName = 'Revora',
  description = 'Empowering businesses with intelligent AI solutions, designed for the future of software engineering.',
  usefulLinks = [
    { label: 'Products', href: '#' },
    { label: 'Careers', href: '#' },
    { label: 'Contact Us', href: '#' },
    { label: 'Privacy Policy', href: '#' },
  ],
  socialLinks = [
    { label: 'Facebook', href: '#', icon: <FacebookIcon /> },
    { label: 'Instagram', href: '#', icon: <InstagramIcon /> },
    { label: 'Twitter (X)', href: '#', icon: <XIcon /> },
  ],
  newsletterTitle = 'Subscribe to our newsletter',
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

  const handleSubscribe = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!email || !onSubscribe || isSubmitting) return;

    setIsSubmitting(true);
    const success = await onSubscribe(email);

    setSubscriptionStatus(success ? 'success' : 'error');
    setIsSubmitting(false);

    if (success) {
      setEmail('');
    }

    // Reset the status message after 3 seconds
    setTimeout(() => {
      setSubscriptionStatus('idle');
    }, 3000);
  };

  return (
    <footer className={cn('bg-muted/50 text-foreground border-t border-border mt-auto', className)} {...props}>
      <div className="container mx-auto grid grid-cols-1 gap-8 px-6 py-16 md:grid-cols-2 lg:grid-cols-4 lg:gap-12">
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
                  className="text-sm text-muted-foreground transition-colors hover:text-primary"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </div>

        {/* Follow Us */}
        <div className="md:justify-self-center">
          <h3 className="mb-4 text-base font-semibold">Follow Us</h3>
          <ul className="space-y-3">
            {socialLinks.map((link) => (
              <li key={link.label}>
                <a
                  href={link.href}
                  aria-label={link.label}
                  className="flex items-center gap-3 text-sm text-muted-foreground transition-colors hover:text-primary group"
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
          <h3 className="mb-4 text-base font-semibold">{newsletterTitle}</h3>
          <form onSubmit={handleSubscribe} className="relative w-full max-w-sm">
            <div className="relative flex rounded-md">
              <Input
                type="email"
                placeholder="Your email address"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isSubmitting || subscriptionStatus !== 'idle'}
                required
                aria-label="Email for newsletter"
                className="pr-28 h-11"
              />
              <Button
                type="submit"
                disabled={isSubmitting || subscriptionStatus !== 'idle'}
                className="absolute right-0 top-0 h-full rounded-l-none px-5"
              >
                {isSubmitting ? 'Subscribing...' : 'Subscribe'}
              </Button>
            </div>
            {/* Advanced Animation Overlay */}
            {(subscriptionStatus === 'success' || subscriptionStatus === 'error') && (
              <div
                key={subscriptionStatus} // Re-trigger animation on status change
                className="animate-in fade-in zoom-in-95 absolute inset-0 flex items-center justify-center rounded-md bg-background/80 text-center backdrop-blur-md border border-border"
              >
                {subscriptionStatus === 'success' ? (
                  <span className="font-semibold text-green-500">Subscribed! 🎉</span>
                ) : (
                  <span className="font-semibold text-destructive">Failed. Try again.</span>
                )}
              </div>
            )}
          </form>
        </div>
      </div>

      {/* Bottom Copyright */}
      <div className="border-t border-border py-6 text-center text-sm text-muted-foreground">
        © {new Date().getFullYear()} {companyName}. All rights reserved.
      </div>
    </footer>
  );
};
