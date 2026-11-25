'use client';

import { useRef } from 'react';
import { GithubIcon, type GithubIconHandle } from '@animateicons/react/lucide';
import {
  ExternalLink,
  LayersIcon,
  ShieldCheck,
  ArrowRight,
  CheckCircle2,
  Clock3,
} from 'lucide-react';
import { useThemeStore } from '@/store/useThemeStore';
import { cn } from '@/lib/utils';
import { buttonVariants } from '@/components/ui/button';
import { Reveal } from '@/components/home/reveal';

export function SetupGuide() {
  const githubIconRef = useRef<GithubIconHandle>(null);
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

  const steps = [
    {
      step: '01',
      title: 'Sign In to Revora',
      description: 'Sign in with your GitHub account to access your AI code review dashboard.',
      icon: LayersIcon,
      href: '/login',
      external: false,
      action: (
        <span
          className={cn(
            buttonVariants({ variant: 'outline', size: 'sm' }),
            'mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 border-border px-4 text-xs font-medium text-foreground transition-colors group-hover:border-[var(--ember-border)] group-hover:text-[var(--ember-ink)] sm:w-auto',
          )}
        >
          Sign In
          <ArrowRight size={14} aria-hidden="true" />
        </span>
      ),
    },
    {
      step: '02',
      title: 'Install GitHub App',
      description: 'Install the Revora PR app on your GitHub account or organization.',
      icon: GithubIcon,
      href: 'https://github.com/apps/revora-pr',
      external: true,
      action: (
        <span
          className={cn(
            buttonVariants({ size: 'sm' }),
            'setup-install-btn mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 border-0 px-4 text-xs font-medium text-white transition-all sm:w-auto',
          )}
        >
          <GithubIcon ref={githubIconRef} size={15} isAnimated={false} />
          Install Revora-PR
          <ExternalLink size={13} className="ml-0.5 opacity-80" aria-hidden="true" />
        </span>
      ),
    },
    {
      step: '03',
      title: 'Select Repositories',
      description:
        'Select the repositories you want to connect. Revora will automatically review every new Pull Request!',
      icon: ShieldCheck,
      href: null,
      external: false,
      action: (
        <div className="mt-3 inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-success/20 bg-success/10 px-3 py-1.5 text-xs font-semibold text-success">
          <CheckCircle2 size={14} className="text-success" aria-hidden="true" />
          Auto-Review Ready
        </div>
      ),
    },
  ];

  return (
    <section className="mx-auto w-full max-w-5xl px-6 py-12">
      <Reveal>
        <div className="mb-10 space-y-3 text-center">
          <div className="flex flex-wrap items-center justify-center gap-2">
            <div className="inline-flex items-center rounded-full border border-[var(--ember-border)] bg-[var(--ember-soft)] px-3.5 py-1 text-xs font-semibold text-[var(--ember-ink)]">
              Quick setup guide
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-1 text-[11px] font-semibold text-muted-foreground">
              <Clock3 size={12} aria-hidden="true" />
              ~2 min
            </span>
          </div>
          <h2
            className="text-3xl font-extrabold tracking-tight text-foreground md:text-4xl"
            style={{ fontFamily: 'var(--font-oxanium, inherit)' }}
          >
            Connect Your Repositories in 3 Steps
          </h2>
          <p className="mx-auto max-w-xl text-sm text-muted-foreground md:text-base">
            Start receiving automated AI feedback on your pull requests in less than 2 minutes.
          </p>
        </div>
      </Reveal>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {steps.map((item, idx) => {
          const StepIcon = item.icon;
          const cardClass = cn(
            'group flex h-full flex-col justify-between rounded-2xl border p-6 text-left backdrop-blur-xl transition-all duration-300 hover:-translate-y-1 hover:border-[var(--ember-border)] hover:shadow-xl motion-reduce:transform-none',
            'bg-surface-1/70 focus-visible:ring-2 focus-visible:ring-[#ff5a2c] focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none',
            isLight ? 'border-border shadow-slate-200/50' : 'border-white/[0.08] shadow-black/20',
          );

          const body = (
            <>
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <span className="rounded-md border border-[var(--ember-border)] bg-[var(--ember-soft)] px-2.5 py-1 font-mono text-xs font-bold tracking-widest text-[var(--ember-ink)]">
                    {item.step}
                  </span>
                  <div className="feature-icon flex h-10 w-10 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-105 motion-reduce:transform-none">
                    <StepIcon size={18} aria-hidden="true" />
                  </div>
                </div>

                <div>
                  <h3 className="text-lg font-bold text-foreground transition-colors group-hover:text-[var(--ember-ink)]">
                    {item.title}
                  </h3>
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground md:text-sm">
                    {item.description}
                  </p>
                </div>
              </div>

              <div className="mt-6 border-t border-border/60 pt-4">{item.action}</div>
            </>
          );

          return (
            <Reveal key={item.step} delay={idx * 0.08} className="setup-step h-full">
              {item.href ? (
                <a
                  href={item.href}
                  {...(item.external
                    ? { target: '_blank', rel: 'noopener noreferrer' }
                    : {})}
                  className={cardClass}
                  onMouseEnter={() => item.external && githubIconRef.current?.startAnimation()}
                  onMouseLeave={() => item.external && githubIconRef.current?.stopAnimation()}
                >
                  {body}
                </a>
              ) : (
                <div className={cardClass}>{body}</div>
              )}
            </Reveal>
          );
        })}
      </div>
    </section>
  );
}
