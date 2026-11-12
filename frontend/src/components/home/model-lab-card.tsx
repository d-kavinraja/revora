'use client';

import Image from 'next/image';
import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import GlareHover from '@/components/ui/GlareHover';
import './model-lab-card.css';

export function ModelLabCard() {
  return (
    <GlareHover
      width="100%"
      height="100%"
      borderRadius="clamp(12px, 1.52vh, 18px)"
      mode="hover"
      variant="streak"
      glareColor="#fed7aa"
      glareOpacity={0.16}
      glareSize={22}
      softness={0.45}
      glareAngle={-45}
      blendMode="screen"
      rimGlint={false}
      transitionDuration={380}
      className="ml-glare"
    >
      <div className="ml-card-inner">
        <div className="ml-media">
          <Image
            src="/assets/model-lab-ai.svg"
            alt="Model Lab AI illustration"
            fill
            unoptimized
            priority={false}
            sizes="(max-width: 619px) 44vw, 215px"
          />
          <span className="ml-badge">NEW</span>
        </div>
        <p className="ml-title">Model Lab is live</p>
        <p className="ml-copy">Build, test, and manage custom AI &amp; deep learning models — free.</p>
        <Link href="/model-lab" className="ml-cta">
          Try it free
          <ArrowRight size={13} strokeWidth={2.4} aria-hidden="true" />
        </Link>
      </div>
    </GlareHover>
  );
}
