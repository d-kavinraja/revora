'use client';

import { ASSETS } from './assets';
import { BloomProviders } from './bloom-providers';
import { Split } from './bloom-split';

/**
 * Fact-derived stats only — no fabricated user metrics:
 * 9 supported AI providers (the provider list shipped with the product),
 * 2 minutes to a first review, 100% repository context coverage,
 * 100% of findings verified against the repository before they are posted.
 */
const CARDS = [
  { label: 'AI Providers', to: 9, dec: 0, suf: '', initial: '0' },
  { label: 'Min to First Review', to: 2, dec: 0, suf: '', initial: '0' },
  { label: 'Repo Context Coverage', to: 100, dec: 0, suf: '%', initial: '0%' },
  { label: 'Findings Verified', to: 100, dec: 0, suf: '%', initial: '0%' },
] as const;

export function BloomStats() {
  return (
    <section className="stats" id="stats">
      <div className="sq-field" data-count="22" aria-hidden="true" />

      <div className="tree-wrap" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element -- remote CloudFront watercolor asset */}
        <img id="tree" className="tree" src={ASSETS.TREE} alt="" />
      </div>

      <div className="stats-inner">
        <span className="pill reveal">Open source · Bring your own key</span>

        <Split className="h2 split stats-title">
          Repository-aware review,
          <br />
          on every pull request.
        </Split>

        <div className="cards">
          {CARDS.map((card) => (
            <div
              key={card.label}
              className="card"
              data-to={card.to}
              data-dec={card.dec}
              data-suf={card.suf}
            >
              <small>{card.label}</small>
              <b>{card.initial}</b>
            </div>
          ))}
        </div>

        <div className="cards-shadow" aria-hidden="true" />

        <div className="logos-wrap">
          <div className="band" id="band" aria-hidden="true" />
          <BloomProviders />
        </div>
      </div>
    </section>
  );
}
