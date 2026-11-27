'use client';

import { useState } from 'react';

import { REVORA } from '@/lib/site';
import { ASSETS } from './assets';
import { Split } from './bloom-split';

const FILTERS = ['All', 'High', 'Medium', 'Low'] as const;
type Filter = (typeof FILTERS)[number];

/** Illustrative findings, shown against real paths in this repository. */
const FINDINGS = [
  {
    id: 'f1',
    severity: 'High',
    title: 'Timeout is not carried through the fallback call',
    path: 'backend/app/ai/llm.py',
    line: 210,
    detail:
      'The retry branch rebuilds the request without the configured deadline. Confirmed against the registry lookup at this line and the routing preference table.',
  },
  {
    id: 'f2',
    severity: 'Medium',
    title: 'Unverified findings are kept when validation is inconclusive',
    path: 'backend/app/verification/engine.py',
    line: 123,
    detail:
      'When the validator cannot locate a line, the finding is still attached to the review. Confidence is downgraded, but the comment is posted.',
  },
  {
    id: 'f3',
    severity: 'Low',
    title: 'Duplicate webhook deliveries are not de-duplicated',
    path: 'backend/app/github/webhooks.py',
    line: 460,
    detail:
      'A retried pull request event can schedule a second review. HMAC verification is intact; only the delivery identifier is unused.',
  },
] as const;

const GRAPH_MODULES = [
  'imports',
  'call graph',
  'module',
  'API',
  'config',
  'DB',
  'tests',
] as const;

export function BloomPreview() {
  const [active, setActive] = useState<Filter>('All');
  const [hasFiltered, setHasFiltered] = useState(false);
  const visible =
    active === 'All' ? FINDINGS : FINDINGS.filter((finding) => finding.severity === active);

  return (
    <section className="preview" id="preview">
      <div className="sq-field" data-count="18" aria-hidden="true" />

      <div className="preview-cloud" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element -- remote CloudFront watercolor asset */}
        <img className="drift-b" src={ASSETS.CLOUD_B} alt="" />
        <div className="glass" style={{ left: '12%', top: '30%', width: '16%' }} />
        <div className="glass" style={{ left: '34%', top: '58%', width: '12%' }} />
        <div className="glass" style={{ left: '58%', top: '22%', width: '14%' }} />
      </div>

      <div className="section-head">
        <span className="pill reveal">Verified PR Review</span>
        <Split className="h2 split">See what lands on your pull request.</Split>
      </div>

      <div className="preview-grid">
        <article className="preview-card context-card reveal-card">
          <span className="pill">Repository context</span>
          <h3>Revora reads the repo, not just the diff.</h3>
          <p>
            Every pull request starts with a whole-repository index: 17 detectors and 8
            code-graph modules. Retrieval feeds only the diff-relevant files to your model,
            so comments are grounded in the code that actually exists.
          </p>

          <div className="code-tree tree-box" aria-hidden="true">
            <span className="tree-root">revora/</span>
            <span className="file-path">├── backend/app/ai/llm.py</span>
            <span className="file-path">├── backend/app/verification/engine.py</span>
            <span className="file-path">├── backend/app/github/webhooks.py</span>
            <span className="file-path">├── frontend/src/app/(dashboard)/chat/</span>
            <span className="file-path">└── docker-compose.yml</span>
          </div>

          <div className="graph-chips" aria-label="Code graph modules">
            {GRAPH_MODULES.map((module) => (
              <span className="graph-chip" key={module}>
                {module}
              </span>
            ))}
          </div>

          <div className="pipeline pipeline-box" aria-label="Review pipeline">
            <span className="pipeline-title">Review pipeline</span>
            <ol className="pipeline-list">
              <li>
                <span>1</span> HMAC Webhook &amp; Clone
              </li>
              <li>
                <span>2</span> 17 Detectors + 8 Code-Graph Modules
              </li>
              <li>
                <span>3</span> Machine-Verified PR Comment · Self-Hosted Docker Compose
              </li>
            </ol>
          </div>

          <div className="card-links">
            <a href={REVORA.github.repo} target="_blank" rel="noopener noreferrer">
              View repository ↗
            </a>
            <a href={REVORA.github.readme} target="_blank" rel="noopener noreferrer">
              Read the README ↗
            </a>
          </div>
        </article>

        <article className="preview-card review-card reveal-card">
          <div className="review-top preview-card-head">
            <span className="pill">Example review</span>
            <span className="review-pr">PR #128 · provider fallback</span>
          </div>

          <div className="review-tabs" role="group" aria-label="Filter findings by severity">
            {FILTERS.map((filter) => (
              <button
                type="button"
                className={`pill filter-pill${active === filter ? ' is-active' : ''}`}
                aria-pressed={active === filter}
                onClick={() => {
                  setActive(filter);
                  setHasFiltered(true);
                }}
                key={filter}
              >
                {filter}
              </button>
            ))}
          </div>

          <ul className={`finding-list${hasFiltered ? ' is-filtered' : ''}`} key={active}>
            {visible.map((finding) => (
              <li className="finding finding-card" key={finding.id}>
                <span className="finding-sev" data-sev={finding.severity}>
                  {finding.severity}
                </span>
                <div className="finding-body">
                  <strong>{finding.title}</strong>
                  <code className="file-path">
                    {finding.path}:{finding.line}
                  </code>
                  <p>{finding.detail}</p>
                  <span className="verified-badge">✓ Machine Verified</span>
                </div>
              </li>
            ))}
          </ul>

          <p className="review-note">
            Illustrative review preview — findings are examples, not live data.
          </p>
        </article>
      </div>
    </section>
  );
}
