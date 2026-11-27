'use client';

import { REVORA } from '@/lib/site';
import { ASSETS } from './assets';
import { Split } from './bloom-split';

export function BloomCta() {
  return (
    <section className="cta" id="cta">
      <div className="sq-field" data-count="16" aria-hidden="true" />

      <div className="cta-img">
        {/* eslint-disable-next-line @next/next/no-img-element -- remote CloudFront watercolor asset */}
        <img id="ctaImg" src={ASSETS.NIGHT} alt="Moonlit cherry blossom valley" />
      </div>

      <div className="petals" id="petals" aria-hidden="true" />

      <div className="cta-card" id="ctaCard">
        <span className="pill">Open source, BYOK</span>
        <Split as="h2" className="h2 split">
          Ship PRs you can trust.
        </Split>
        <p className="reveal">
          Install Revora-PR and get a repository-aware review on your next pull request.
        </p>
        <a
          className="btn reveal"
          href={REVORA.github.app}
          target="_blank"
          rel="noopener noreferrer"
        >
          Install Revora-PR
        </a>
      </div>
    </section>
  );
}
