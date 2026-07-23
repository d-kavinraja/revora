'use client';

import { motion } from "framer-motion";
import Link from "next/link";
import Image from "next/image";
import { buttonVariants } from "@/components/ui/button";
import { GithubIcon, ShieldCheckIcon, ZapIcon, GitBranchIcon } from "@animateicons/react/lucide";
import { useRef } from "react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { cn } from "@/lib/utils";

import { useThemeStore } from '@/store/useThemeStore';
import { StickyBanner } from '@/components/ui/sticky-banner';
import { SetupGuide } from '@/components/shared/setup-guide';
import GridDistortion from '@/components/ui/GridDistortion';

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
  const githubIconRef = useRef<any>(null);
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground relative overflow-hidden">
      {/* Top Banner */}
      <StickyBanner className="bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 text-white font-medium text-xs md:text-sm shadow-md">
        <p className="mx-0 max-w-[90%] drop-shadow-sm flex items-center justify-center gap-2 flex-wrap text-center py-1">
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

      {/* GridDistortion Background */}
      <div className={cn(
        "fixed inset-0 pointer-events-none z-0 transition-all duration-500",
        isLight ? "opacity-20 mix-blend-multiply" : "opacity-30 mix-blend-screen"
      )}>
        <GridDistortion
          imageSrc="https://picsum.photos/1920/1080?grayscale"
          grid={12}
          mouse={0.15}
          strength={0.18}
          relaxation={0.92}
        />
      </div>



      <header className="flex items-center justify-between p-6 z-10 border-b border-border bg-background/50 backdrop-blur-md sticky top-0">
        <div className="flex items-center gap-2.5">
          <Image
            src="/revora-logo.png"
            alt="Revora Logo"
            width={32}
            height={32}
            className="rounded-lg object-contain shrink-0 shadow-[0_0_16px_rgba(99,102,241,0.3)]"
          />
          <span className="font-bold text-xl tracking-tight" style={{ fontFamily: 'var(--font-oxanium, inherit)' }}>Revora</span>
        </div>
        <nav className="flex items-center gap-3">
          <ThemeToggle />
          <Link
            href="/login"
            className={cn(buttonVariants({ variant: "ghost" }), "text-muted-foreground hover:text-foreground hover:bg-white/[0.04]")}
          >
            Sign In
          </Link>
          <Link
            href="/register"
            className={cn(buttonVariants({ variant: "default" }), "bg-foreground text-background hover:bg-foreground/90")}
          >
            Get Started
          </Link>
        </nav>
      </header>

      <main className="flex-1 z-10 space-y-12">
        {/* Hero */}
        <section className="flex flex-col items-center justify-center p-6 pt-16 pb-16 text-center">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: 'easeOut' }}
            className="max-w-4xl space-y-6"
          >
            <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight leading-[1.1] drop-shadow-md" style={{ fontFamily: 'var(--font-oxanium, inherit)' }}>
              The Ultimate <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-brand to-purple-500">AI Code Reviewer</span>
            </h1>
            <p className="text-lg md:text-xl text-foreground/80 max-w-2xl mx-auto leading-relaxed drop-shadow-sm">
              Supercharge your engineering team with context-aware, repository-wide intelligence. Catch bugs, secure endpoints, and optimize performance before merging.
            </p>
            <div className="flex items-center justify-center gap-4 pt-4">
              <a
                href="https://github.com/apps/revora-pr"
                target="_blank"
                rel="noopener noreferrer"
                onMouseEnter={() => githubIconRef.current?.startAnimation()}
                onMouseLeave={() => githubIconRef.current?.stopAnimation()}
                className={cn(buttonVariants({ size: "lg" }), "h-12 px-7 text-base bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white shadow-[0_0_24px_rgba(147,51,234,0.3)] border-0 transition-all hover:scale-[1.02] gap-2")}
              >
                Install Revora-PR App
                <GithubIcon ref={githubIconRef} size={18} isAnimated={false} />
              </a>
            </div>
          </motion.div>
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
                <div key={i} className="rounded-xl border border-border bg-surface-1/50 backdrop-blur-md p-6 text-center space-y-3 shadow-lg shadow-black/5">
                  <div className="w-10 h-10 rounded-lg bg-brand/10 flex items-center justify-center mx-auto text-brand">
                    <Icon size={20} />
                  </div>
                  <h3 className="font-semibold text-foreground drop-shadow-sm">{feature.title}</h3>
                  <p className="text-sm text-foreground/80 leading-relaxed">{feature.description}</p>
                </div>
              );
            })}
          </motion.div>
        </section>
      </main>

      <footer className="border-t border-border p-6 text-center text-xs text-muted-foreground z-10">
        Revora &mdash; AI Code Review
      </footer>
    </div>
  );
}
