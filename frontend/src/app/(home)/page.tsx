'use client';

import { motion } from "framer-motion";
import { ShieldCheckIcon, ZapIcon, GitBranchIcon } from "@animateicons/react/lucide";
import { cn } from "@/lib/utils";

import { useThemeStore } from '@/store/useThemeStore';
import { StickyBanner } from '@/components/ui/sticky-banner';
import { SetupGuide } from '@/components/shared/setup-guide';
import { AnnouncementBanner } from '@/components/landing/announcement-banner';
import { MaintenanceBanner } from '@/components/shared/maintenance-banner';
import Waves from '@/components/ui/Waves';
import { Footer } from '@/components/ui/footer';
import { DataSignalHero } from '@/components/home/data-signal-hero';
import { LogoLoop } from '@/components/ui/logo-loop';
import { Gemini, OpenAI, Claude, DeepSeek, Groq, OpenRouter, Azure, Mistral, Cohere, Ollama } from '@lobehub/icons';

const apiLogos = [
  { node: <Gemini.Color />, title: "Google Gemini" },
  { node: <OpenAI />, title: "OpenAI" },
  { node: <Claude.Color />, title: "Anthropic Claude" },
  { node: <DeepSeek.Color />, title: "DeepSeek" },
  { node: <Groq />, title: "Groq" },
  { node: <OpenRouter className="text-blue-500" />, title: "OpenRouter" },
  { node: <Azure.Color />, title: "Azure OpenAI" },
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

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground relative overflow-hidden">
      {/* Top Banner */}
      <StickyBanner className="bg-zinc-950 border-b border-zinc-800 text-zinc-300 font-mono text-xs md:text-sm">
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

      {/* Phase 7 — landing announcements (graceful degradation: absent if backend down) */}
      <AnnouncementBanner />

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

      <main className="flex-1 z-10 space-y-12" id="setup">

        {/* Supported AI Models Loop */}
        <section className="w-full overflow-hidden pb-12 pt-4">
          <div className="max-w-7xl mx-auto px-6 mb-8 text-center">
            <p className="text-sm font-medium text-muted-foreground uppercase tracking-widest">
              Powered by industry-leading AI models
            </p>
          </div>
          <div style={{ height: '60px', position: 'relative' }}>
            <LogoLoop
              logos={apiLogos}
              speed={120}
              direction="left"
              logoHeight={40}
              gap={60}
              scaleOnHover={true}
              fadeOut={true}
              fadeOutColor={isLight ? '#ffffff' : '#0b0b0b'}
              ariaLabel="Supported AI Providers"
            />
          </div>
        </section>

        {/* 3-Step Setup Guide */}
        <SetupGuide />

        {/* Features */}
        <section className="max-w-5xl mx-auto px-6 pb-24">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.2, ease: 'easeOut' }}
            className="grid grid-cols-1 md:grid-cols-3 gap-4"
          >
            {features.map((feature, i) => {
              const Icon = feature.icon;
              return (
                <div key={i} className={cn(
                  "rounded-xl border backdrop-blur-md p-6 text-center space-y-3 transition-all duration-300",
                  isLight ? "border-border bg-surface-1/70 shadow-slate-200/50" : "border-zinc-800 bg-zinc-950/80 shadow-black/20"
                )}>
                  <div className={cn(
                    "w-10 h-10 rounded-lg flex items-center justify-center mx-auto transition-colors",
                    isLight ? "bg-black/[0.05] text-foreground" : "bg-zinc-800 text-zinc-100"
                  )}>
                    <Icon size={20} />
                  </div>
                  <h3 className={cn("font-semibold transition-colors", isLight ? "text-foreground" : "text-zinc-100")}>{feature.title}</h3>
                  <p className={cn("text-sm font-mono leading-relaxed transition-colors", isLight ? "text-muted-foreground" : "text-zinc-400")}>{feature.description}</p>
                </div>
              );
            })}
          </motion.div>
        </section>
      </main>

      <Footer
        logoSrc="/revora-logo.png"
        className="z-20 relative bg-background/95 backdrop-blur-xl border-t border-border shadow-[0_-8px_30px_rgba(0,0,0,0.12)]"
      />
    </div>
  );
}
