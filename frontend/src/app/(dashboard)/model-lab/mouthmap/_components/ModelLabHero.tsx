'use client';

import { motion, useReducedMotion } from 'motion/react';
import { CirclePlay, Film, Microscope } from 'lucide-react';
import Link from 'next/link';

export function ModelLabHero() {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <nav aria-label="Breadcrumb" className="text-xs text-foreground/60 mb-3">
        <Link href="/dashboard" className="hover:text-foreground transition-colors" aria-label="Go to dashboard">
          Home
        </Link>
        <span className="mx-1.5" aria-hidden="true">
          &gt;
        </span>
        <Link href="/model-lab" className="hover:text-foreground transition-colors" aria-label="Go to Model Lab">
          Model Lab
        </Link>
        <span className="mx-1.5" aria-hidden="true">
          &gt;
        </span>
        <span aria-current="page" className="text-foreground font-medium">
          MouthMap Model
        </span>
      </nav>
      <div className="model-lab-hero rounded-xl border border-border p-5 md:p-7">
        <div className="flex flex-col lg:flex-row lg:items-center gap-6">
          <div className="min-w-0 flex-1">
            <div className="ml-anim-text min-w-0">
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight flex items-center gap-2 flex-wrap">
                MouthMap Model
                <span className="ml-hero-beta text-xs font-semibold px-2 py-0.5 rounded-full bg-ai-purple/20 text-ai-purple border border-ai-purple/30">
                  v1
                </span>
                <span className="ml-hero-beta text-xs font-semibold px-2 py-0.5 rounded-full bg-ai-cyan/20 text-ai-cyan border border-ai-cyan/30">
                  Beta
                </span>
              </h1>
              <p className="text-foreground/75 text-sm mt-2 leading-relaxed">
                Revora&apos;s first computer vision model. Upload or select a supported video to test the model and inspect its predictions.
              </p>
              <p className="text-foreground/65 text-xs mt-0.5 leading-relaxed">
                Upload test videos, run inference, and visualize results with detailed insights.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 md:gap-4 lg:max-w-[460px] w-full">
            <div className="ml-anim-card flex sm:flex-col items-center sm:text-left gap-2.5 rounded-lg bg-surface-2 p-3">
              <span className="ml-hero-chip shrink-0 w-9 h-9 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center">
                <Film size={18} />
              </span>
              <span className="min-w-0">
                <span className="block text-base font-semibold tracking-tight leading-tight">Video Testing</span>
                <span className="block text-sm text-foreground/70 leading-relaxed mt-1">Upload and test real-world videos</span>
              </span>
            </div>
            <div className="ml-anim-card flex sm:flex-col items-center sm:text-left gap-2.5 rounded-lg bg-surface-2 p-3">
              <span className="ml-hero-chip shrink-0 w-9 h-9 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center">
                <Microscope size={18} />
              </span>
              <span className="min-w-0">
                <span className="block text-base font-semibold tracking-tight leading-tight">Model Insights</span>
                <span className="block text-sm text-foreground/70 leading-relaxed mt-1">View predictions and confidence</span>
              </span>
            </div>
            <div className="ml-anim-card flex sm:flex-col items-center sm:text-left gap-2.5 rounded-lg bg-surface-2 p-3">
              <span className="ml-hero-chip shrink-0 w-9 h-9 rounded-lg bg-ai-cyan/10 text-ai-cyan flex items-center justify-center">
                <CirclePlay size={18} />
              </span>
              <span className="min-w-0">
                <span className="block text-base font-semibold tracking-tight leading-tight">Iterate Faster</span>
                <span className="block text-sm text-foreground/70 leading-relaxed mt-1">Improve and validate results</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
