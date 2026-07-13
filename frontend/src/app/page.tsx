'use client';

import { motion } from "framer-motion";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { GithubIcon, ShieldCheckIcon, ZapIcon, GitBranchIcon } from "@animateicons/react/lucide";
import { useRef } from "react";

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

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground relative overflow-hidden">
      {/* Background gradients */}
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-brand/15 blur-[140px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-purple-600/10 blur-[140px] rounded-full pointer-events-none" />
      {/* Subtle grid */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.015)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.015)_1px,transparent_1px)] bg-[size:64px_64px] pointer-events-none" />

      <header className="flex items-center justify-between p-6 z-10 border-b border-border bg-background/50 backdrop-blur-md sticky top-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 via-brand to-purple-600 flex items-center justify-center shadow-[0_0_16px_rgba(99,102,241,0.3)]">
            <span className="font-bold text-lg text-white">R</span>
          </div>
          <span className="font-bold text-xl tracking-tight">Revora</span>
        </div>
        <nav className="flex gap-3">
          <Link href="/login">
            <Button variant="ghost" className="text-muted-foreground hover:text-foreground hover:bg-white/[0.04]">Sign In</Button>
          </Link>
          <Link href="/register">
            <Button className="bg-foreground text-background hover:bg-foreground/90">Get Started</Button>
          </Link>
        </nav>
      </header>

      <main className="flex-1 z-10">
        {/* Hero */}
        <section className="flex flex-col items-center justify-center p-6 pt-20 pb-24 text-center">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: 'easeOut' }}
            className="max-w-4xl space-y-6"
          >
            <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight leading-[1.1]">
              The Ultimate <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-brand to-purple-500">AI Code Reviewer</span>
            </h1>
            <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
              Supercharge your engineering team with context-aware, repository-wide intelligence. Catch bugs, secure endpoints, and optimize performance before merging.
            </p>
            <div className="flex items-center justify-center gap-4 pt-4">
              <Link href="/login">
                <Button
                  size="lg"
                  onMouseEnter={() => githubIconRef.current?.startAnimation()}
                  onMouseLeave={() => githubIconRef.current?.stopAnimation()}
                  className="h-12 px-7 text-base bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white shadow-[0_0_24px_rgba(147,51,234,0.3)] border-0 transition-all hover:scale-[1.02] gap-2"
                >
                  Install GitHub App
                  <GithubIcon ref={githubIconRef} size={18} isAnimated={false} />
                </Button>
              </Link>
            </div>
          </motion.div>
        </section>

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
                <div key={i} className="rounded-xl border border-border bg-surface-1/50 p-6 text-center space-y-3">
                  <div className="w-10 h-10 rounded-lg bg-brand/10 flex items-center justify-center mx-auto text-brand">
                    <Icon size={20} />
                  </div>
                  <h3 className="font-semibold text-foreground">{feature.title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">{feature.description}</p>
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
