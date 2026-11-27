'use client';

import Link from 'next/link';
import { ASSETS } from './assets';
import { BloomGithubPill } from './bloom-github-pill';
import { BloomNav } from './bloom-nav';
import { Split } from './bloom-split';

export function BloomHero() {
  return (
    <section className="hero" id="hero">
      <div className="bloom-header-bar">
        <BloomNav />
        <BloomGithubPill />
      </div>

      <div className="cloud cloud-l" data-par="-60" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element -- remote CloudFront watercolor asset */}
        <img className="drift-a" src={ASSETS.CLOUD_A} alt="" />
      </div>
      <div className="cloud cloud-r" data-par="-90" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element -- remote CloudFront watercolor asset */}
        <img className="drift-b" src={ASSETS.CLOUD_B} alt="" />
      </div>

      <Split as="h1" className="hero-title" id="heroTitle">
        Stop reviewing
        <br />
        <em>diffs blind.</em>
      </Split>

      {/* Mobile-only sign-in pill; same destination as the desktop nav's "Sign in" link. */}
      <div className="hero-cta hidden max-[761px]:flex justify-center mt-5 px-4">
        <Link
          href="/login"
          className="inline-flex items-center justify-center min-h-[46px] px-7 rounded-full border border-[#4d6a10]/35 bg-[#f6f8f1]/90 backdrop-blur-md text-[15px] font-medium tracking-[-0.01em] text-[#3f5710] shadow-[0_8px_22px_rgba(45,62,12,0.12)] transition duration-200 hover:bg-[#fff] active:scale-[0.97]"
        >
          Sign in →
        </Link>
      </div>

      <div className="hero-media" aria-hidden="true">
        <video
          id="heroVideo"
          autoPlay
          muted
          loop
          playsInline
          preload="auto"
          poster={ASSETS.HERO_POSTER}
          src={ASSETS.HERO_VIDEO}
        />
      </div>

      <div className="hero-glass" id="heroGlass" aria-hidden="true" />
    </section>
  );
}
