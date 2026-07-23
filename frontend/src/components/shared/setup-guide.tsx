'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useRef } from 'react';
import { GithubIcon } from '@animateicons/react/lucide';
import { ExternalLink, LayersIcon, ShieldCheck, ArrowRight, CheckCircle2 } from 'lucide-react';
import { useThemeStore } from '@/store/useThemeStore';
import { cn } from '@/lib/utils';
import { buttonVariants } from '@/components/ui/button';

export function SetupGuide() {
  const githubIconRef = useRef<any>(null);
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

  const steps = [
    {
      step: '01',
      title: 'Sign In to Revora',
      description: 'Sign in with your GitHub account to access your AI code review dashboard.',
      icon: LayersIcon,
      action: (
        <Link
          href="/login"
          className={cn(
            buttonVariants({ variant: 'outline', size: 'sm' }),
            'mt-3 w-full sm:w-auto inline-flex items-center justify-center gap-2 border-border text-foreground hover:bg-white/[0.06] hover:text-brand transition-colors text-xs font-medium'
          )}
        >
          Sign In
          <ArrowRight size={14} />
        </Link>
      ),
    },
    {
      step: '02',
      title: 'Install GitHub App',
      description: 'Go to github.com/apps/revora-pr and install the Revora PR app on your GitHub account or organization.',
      icon: GithubIcon,
      action: (
        <a
          href="https://github.com/apps/revora-pr"
          target="_blank"
          rel="noopener noreferrer"
          onMouseEnter={() => githubIconRef.current?.startAnimation()}
          onMouseLeave={() => githubIconRef.current?.stopAnimation()}
          className={cn(
            buttonVariants({ size: 'sm' }),
            'mt-3 w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white shadow-md border-0 text-xs font-medium transition-all hover:scale-[1.02]'
          )}
        >
          <GithubIcon ref={githubIconRef} size={15} isAnimated={false} />
          Install Revora-PR
          <ExternalLink size={13} className="ml-0.5 opacity-80" />
        </a>
      ),
    },
    {
      step: '03',
      title: 'Select Repositories',
      description: 'Select the repositories you want to connect. Revora will automatically review every new Pull Request!',
      icon: ShieldCheck,
      action: (
        <div className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-success/10 border border-success/20 text-success text-xs font-semibold">
          <CheckCircle2 size={14} className="text-success" />
          Auto-Review Ready
        </div>
      ),
    },
  ];

  return (
    <section className="w-full max-w-5xl mx-auto px-6 py-12">
      <div className="text-center space-y-3 mb-10">
        <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-brand/10 border border-brand/20 text-brand text-xs font-semibold uppercase tracking-wider">
          Quick Setup Guide
        </div>
        <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-foreground" style={{ fontFamily: 'var(--font-oxanium, inherit)' }}>
          Connect Your Repositories in 3 Steps
        </h2>
        <p className="text-sm md:text-base text-muted-foreground max-w-xl mx-auto">
          Start receiving automated AI feedback on your pull requests in less than 2 minutes.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {steps.map((item, idx) => {
          const StepIcon = item.icon;
          return (
            <motion.div
              key={item.step}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: idx * 0.15 }}
              className={cn(
                'relative flex flex-col justify-between rounded-2xl border p-6 transition-all duration-300 group',
                'bg-surface-1/70 backdrop-blur-xl hover:border-brand/40 hover:shadow-xl',
                isLight ? 'border-border shadow-slate-200/50' : 'border-white/[0.08] shadow-black/20'
              )}
            >
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold font-mono tracking-widest text-brand px-2.5 py-1 rounded-md bg-brand/10 border border-brand/20">
                    {item.step}
                  </span>
                  <div className="w-9 h-9 rounded-xl bg-white/[0.05] border border-white/[0.08] flex items-center justify-center text-muted-foreground group-hover:text-brand group-hover:bg-brand/10 transition-colors">
                    <StepIcon size={18} />
                  </div>
                </div>

                <div>
                  <h3 className="text-lg font-bold text-foreground group-hover:text-brand transition-colors">
                    {item.title}
                  </h3>
                  <p className="text-xs md:text-sm text-muted-foreground mt-2 leading-relaxed">
                    {item.description}
                  </p>
                </div>
              </div>

              <div className="pt-4 border-t border-border/50 mt-6">
                {item.action}
              </div>
            </motion.div>
          );
        })}
      </div>
    </section>
  );
}
