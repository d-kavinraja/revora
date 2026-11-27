'use client';

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
