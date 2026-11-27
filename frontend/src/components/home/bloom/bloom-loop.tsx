'use client';

import { ASSETS } from './assets';
import { Split } from './bloom-split';

const STEPS = [
  {
    n: '1',
    title: 'PR lands',
    body: 'The Revora-PR GitHub App picks up your pull request — the diff, changed files, and commit context.',
    cloud: ASSETS.CLOUD_B,
  },
  {
    n: '2',
    title: 'Repo deep-read',
    body: 'Revora maps imports, calls, modules, APIs, config and tests, then retrieves the context each finding needs.',
    cloud: ASSETS.CLOUD_A,
  },
  {
    n: '3',
    title: 'Verified findings',
    body: 'Every finding is checked against the repository before it is posted to the PR. Pick models per repo in Model Lab.',
    cloud: ASSETS.CLOUD_B,
  },
] as const;

export function BloomLoop() {
  return (
    <section className="loop" id="loop">
      <div className="loop-cloud" data-par="-50" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element -- remote CloudFront watercolor asset */}
        <img className="drift-a" src={ASSETS.CLOUD_A} alt="" />
        <div className="glass" style={{ left: '6%', top: '30%', width: '15%' }} />
        <div className="glass" style={{ left: '23%', top: '58%', width: '13%' }} />
        <div className="glass" style={{ left: '38%', top: '24%', width: '13%' }} />
      </div>

      <div className="loop-head">
        <span className="pill reveal">How it works</span>
        <Split className="h2 split">
          Revora reads your whole repo
          <br />
          before it reviews a diff.
        </Split>
      </div>

      <div className="track" id="track">
        {STEPS.map((step, index) => (
          <div
            key={step.n}
            className={`panel${index === 0 ? ' is-active' : ''}`}
            tabIndex={0}
            aria-label={`Step ${step.n}: ${step.title}`}
          >
            <div className="panel-in">
              <span className={`num num-${step.n}`}>{step.n}</span>
              <div className="step">
                {/* eslint-disable-next-line @next/next/no-img-element -- remote CloudFront watercolor asset */}
                <img className="mini-cloud" src={step.cloud} alt="" aria-hidden="true" />
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
