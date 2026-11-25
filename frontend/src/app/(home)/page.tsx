'use client';

import type { MouseEvent } from 'react';
import { ShieldCheckIcon, ZapIcon, GitBranchIcon } from "@animateicons/react/lucide";
import { cn } from "@/lib/utils";

import { useThemeStore } from '@/store/useThemeStore';
import { StickyBanner } from '@/components/ui/sticky-banner';
import { SetupGuide } from '@/components/shared/setup-guide';

import { MaintenanceBanner } from '@/components/shared/maintenance-banner';
import Waves from '@/components/ui/Waves';
import { Footer } from '@/components/ui/footer';
import { DataSignalHero } from '@/components/home/data-signal-hero';
import { LogoLoop } from '@/components/ui/logo-loop';
import { Reveal } from '@/components/home/reveal';
import { SampleReview, LandingFaq, FinalCtaBand } from '@/components/home/landing-sections';
import '@/components/home/landing-sections.css';
import { Gemini, OpenAI, Claude, DeepSeek, Groq, OpenRouter, Mistral, Cohere, Ollama } from '@lobehub/icons';

const apiLogos = [
  { node: <Gemini.Color />, title: "Google Gemini" },
  { node: <OpenAI />, title: "OpenAI" },
  { node: <Claude.Color />, title: "Anthropic Claude" },
  { node: <DeepSeek.Color />, title: "DeepSeek" },
  { node: <Groq className="text-[#F55036]" />, title: "Groq" },
  { node: <OpenRouter className="text-[#6566F1]" />, title: "OpenRouter" },
  { node: <Mistral.Color />, title: "Mistral AI" },
  { node: <Cohere.Color />, title: "Cohere" },
  { node: <Ollama />, title: "Ollama" },
];

const features = [
  {
    icon: ZapIcon,
    title: "Instant Analysis",
    description: "AI-powered reviews in seconds, not hours. Get actionable feedback the moment you push.",
  },
  {
    icon: ShieldCheckIcon,
    title: "Security First",
    description: "Catch vulnerabilities, injection risks, and auth flaws before they reach production.",
  },
  {
    icon: GitBranchIcon,
    title: "Repository-Wide Context",
    description: "Understands your entire codebase, not just the diff. Cross-file intelligence for smarter reviews.",
  },
];

export default function LandingPage() {
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

  const handleFeatureGlow = (event: MouseEvent<HTMLDivElement>) => {
    const card = event.currentTarget;
    const rect = card.getBoundingClientRect();
    card.style.setProperty('--glow-x', `${event.clientX - rect.left}px`);
    card.style.setProperty('--glow-y', `${event.clientY - rect.top}px`);
  };

  return (
    <div className="revora-landing flex min-h-[calc(100dvh-var(--revora-announcement-height,0px))] flex-col bg-background text-foreground relative overflow-hidden">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>

      {/* Top Banner */}
      <StickyBanner sticky={false} className="bg-zinc-950 border-b border-zinc-800 text-zinc-300 font-mono text-xs md:text-sm">
        <p className="mx-0 max-w-[90%] flex items-center justify-center gap-2 flex-wrap text-center py-1">
          <span>🚀 <strong>Connect Revora in seconds:</strong> Sign in with GitHub, install <code className="bg-white/20 px-1.5 py-0.5 rounded font-mono text-xs">Revora-PR</code> app & select repositories!</span>
          <a
            href="https://github.com/apps/revora-pr"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-4 hover:text-white/90 font-bold transition-opacity"
          >
            Install App ↗
          </a>
        </p>
      </StickyBanner>

      {/* Maintenance fallback banner (≤5s stale-cache window, C5) */}
      <MaintenanceBanner />



      {/* Waves Background */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <Waves
          lineColor={isLight ? "rgba(0, 0, 0, 0.15)" : "rgba(255, 255, 255, 0.15)"}
          backgroundColor="transparent"
          waveSpeedX={0.02}
          waveSpeedY={0.01}
          waveAmpX={40}
          waveAmpY={20}
          friction={0.9}
          tension={0.01}
          maxCursorMove={120}
          xGap={12}
          yGap={36}
        />
      </div>



      <DataSignalHero />

      <main className="flex-1 z-10 space-y-12" id="main-content">

        {/* Supported AI Models Loop */}
        <section className="w-full overflow-hidden pb-12 pt-4">
          <div className="max-w-7xl mx-auto px-6 mb-8 text-center">
            <p className="text-sm font-medium text-muted-foreground">
              Powered by industry-leading AI models
            </p>
          </div>
          <div className="logo-rail" style={{ height: '60px', position: 'relative' }}>
            <LogoLoop
              logos={apiLogos}
              speed={120}
              direction="left"
              logoHeight={40}
              gap={60}
              pauseOnHover
              scaleOnHover={true}
              fadeOut={true}
              fadeOutColor={isLight ? '#ffffff' : '#0b0b0b'}
              ariaLabel="Supported AI Providers"
              className="landing-logo-loop"
            />
          </div>
        </section>

        {/* 3-Step Setup Guide */}
        <div id="setup" className="scroll-mt-24">
          <SetupGuide />
        </div>

        {/* Features */}
        <section className="max-w-5xl mx-auto px-6 pb-24 scroll-mt-24" id="features">
          <Reveal className="mb-8 space-y-3 text-center">
            <p className="text-xs font-semibold text-[var(--ember-ink)]">Why Revora</p>
            <h2 className="text-3xl font-extrabold tracking-tight text-foreground md:text-4xl" style={{ fontFamily: 'var(--font-oxanium, inherit)' }}>
              Review intelligence, not guesswork.
            </h2>
            <p className="mx-auto max-w-xl text-sm text-muted-foreground md:text-base">
              Repository context, security checks, and model choice in every review.
            </p>
          </Reveal>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {features.map((feature, i) => {
              const Icon = feature.icon;
              return (
                <Reveal key={feature.title} delay={i * 0.08} className="h-full">
                  <article
                    onMouseMove={handleFeatureGlow}
                    className={cn(
                      "feature-glow flex h-full flex-col rounded-xl border p-6 text-center space-y-3 backdrop-blur-md transition-all duration-300 hover:-translate-y-1 hover:border-[#ff5a2c]/40 motion-reduce:transform-none",
                      isLight ? "border-border bg-surface-1/70 shadow-slate-200/50" : "border-zinc-800 bg-zinc-950/80 shadow-black/20"
                    )}
                  >
                    <div className="feature-icon mx-auto flex h-10 w-10 items-center justify-center rounded-lg">
                      <Icon size={20} aria-hidden="true" />
                    </div>
                    <h3 className={cn("font-semibold transition-colors", isLight ? "text-foreground" : "text-zinc-100")}>{feature.title}</h3>
                    <p className={cn("text-sm font-mono leading-relaxed transition-colors", isLight ? "text-muted-foreground" : "text-zinc-400")}>{feature.description}</p>
                  </article>
                </Reveal>
              );
            })}
          </div>
        </section>

        <SampleReview />
        <LandingFaq />
        <FinalCtaBand />
      </main>

      <Footer
        logoSrc="/revora-logo.png"
        className="z-20 relative bg-background/95 backdrop-blur-xl border-t border-border shadow-[0_-8px_30px_rgba(0,0,0,0.12)]"
      />
    </div>
  );
}
