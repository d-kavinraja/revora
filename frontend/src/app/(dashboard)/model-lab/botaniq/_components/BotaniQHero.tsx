'use client';

import { motion, useReducedMotion } from 'motion/react';
import { FlaskConical, ImageIcon, Leaf, Trophy } from 'lucide-react';
import Link from 'next/link';

export function BotaniQHero() {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <nav aria-label="Breadcrumb" className="text-xs text-foreground/70 mb-3">
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
          BotaniQ
        </span>
      </nav>
      <div className="model-lab-hero rounded-xl border border-border p-5 md:p-7" style={{ ['--brand' as string]: 'oklch(0.55 0.18 155)' }}>
        <div className="flex flex-col lg:flex-row lg:items-center gap-6">
          <div className="min-w-0 flex-1">
            <div className="ml-anim-text min-w-0">
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight flex items-center gap-2 flex-wrap text-foreground">
                <span className="ml-hero-mark w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-600 to-emerald-400 flex items-center justify-center text-white shrink-0">
                  <Leaf size={20} />
                </span>
                BotaniQ
                <span className="ml-hero-beta text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 border border-emerald-500/40">
                  v1.0
                </span>
                <span className="ml-hero-beta text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-800 dark:text-amber-300 border border-amber-500/40">
                  Beta
                </span>
              </h1>
              <p className="text-foreground/80 text-sm mt-2 leading-relaxed max-w-[60ch]">
                Medicinal herb classifier — upload an image or paste a URL to identify plant and leaf species with confidence scores.
              </p>
              <p className="text-foreground/75 text-xs mt-0.5 leading-relaxed">
                Upload test images, run inference, and visualize predictions with top-5 results.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 md:gap-4 lg:max-w-[460px] w-full">
            {[
              { icon: <ImageIcon size={18} />, label: 'Image Input', sub: 'Upload, URL, or dataset' },
              { icon: <Trophy size={18} />, label: 'Top-5 Results', sub: 'Ranked by confidence' },
              { icon: <FlaskConical size={18} />, label: 'VGG16 Model', sub: '224×224 RGB inference' },
            ].map(({ icon, label, sub }) => (
              <div key={label} className="ml-anim-card flex sm:flex-col items-center sm:text-left gap-2.5 rounded-lg bg-surface-2 p-3">
                <span className="ml-hero-chip shrink-0 w-9 h-9 rounded-lg bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 flex items-center justify-center">
                  {icon}
                </span>
                <span className="min-w-0">
                  <span className="block text-base font-semibold tracking-tight leading-tight text-foreground">{label}</span>
                  <span className="block text-sm text-foreground/80 leading-relaxed mt-1">{sub}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
