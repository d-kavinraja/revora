'use client';

import { ArrowRight, CheckCircle2, ChevronDown, FileCode2, ShieldCheck } from 'lucide-react';
import { REVORA } from '@/lib/site';
import { Reveal } from './reveal';
import './landing-sections.css';

const findings = [
  {
    severity: 'High',
    className: 'sev-high',
    path: 'services/auth/session.py',
    line: 42,
    detail:
      'Session tokens are compared with ==. Use a constant-time comparison and reject expired sessions before lookup.',
  },
  {
    severity: 'Medium',
    className: 'sev-medium',
    path: 'lib/github/webhooks.ts',
    line: 118,
    detail:
      'Signature verification accepts deliveries without a timestamp. Reject payloads older than five minutes.',
  },
  {
    severity: 'Low',
    className: 'sev-low',
    path: 'workers/review_queue.py',
    line: 87,
    detail:
      'The retry loop can exceed the repository token budget. Cap attempts and reuse cached context between runs.',
  },
];

const faqs = [
  {
    question: 'Does Revora read only the diff?',
    answer:
      'No. Revora builds a map of the repository first — imports, calls, modules, APIs, config and tests — then retrieves the context a finding needs before the model reviews the change.',
  },
  {
    question: 'Do I need my own LLM API key?',
    answer:
      'Yes. Revora is BYOK: add a provider key in Settings, choose a model per repository, and reviews run against your account.',
  },
  {
    question: 'Which providers can I use today?',
    answer:
      'Gemini, Groq, Cohere, OpenRouter, Ollama Cloud and NVIDIA NIM are available for reviews. OpenAI, Anthropic, DeepSeek and Mistral are under testing.',
  },
  {
    question: 'Is Revora free and open source?',
    answer:
      'Yes. The code is MIT-licensed on GitHub. You can use the hosted app or self-host with Docker Compose.',
  },
  {
    question: 'Where do review comments appear?',
    answer:
      'Revora posts the review to the pull request that triggered it. Every finding is checked against the repository before it is reported.',
  },
];

export function SampleReview() {
  return (
    <section
      id="sample-review"
      aria-labelledby="sample-review-title"
      className="mx-auto max-w-5xl scroll-mt-24 px-6 pb-24"
    >
      <Reveal>
        <div className="mb-8 space-y-3 text-center">
          <p className="text-xs font-semibold text-[var(--ember-ink)]">
            Sample review
          </p>
          <h2
            id="sample-review-title"
            className="text-3xl font-extrabold tracking-tight text-foreground md:text-4xl"
            style={{ fontFamily: 'var(--font-oxanium, inherit)' }}
          >
            See what lands on your PR
          </h2>
          <p className="mx-auto max-w-xl text-sm text-muted-foreground md:text-base">
            A short, verified review with the file and line behind every finding.
          </p>
        </div>
      </Reveal>

      <Reveal delay={0.1}>
        <article
          className="sample-review-card mx-auto max-w-3xl overflow-hidden rounded-2xl border border-border shadow-lg shadow-black/5"
          aria-label="Sample Revora pull request review"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-4 sm:px-5">
            <div className="flex min-w-0 items-center gap-3">
              <span className="feature-icon flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                <FileCode2 size={17} aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <p className="truncate font-mono text-[11px] text-muted-foreground">
                  d-kavinraja/revora
                </p>
                <h3 className="truncate text-sm font-semibold text-foreground">
                  PR #1842 · Harden webhook auth
                </h3>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-border px-2.5 py-1 text-[10px] font-semibold text-muted-foreground">
                Sample
              </span>
              <span className="verified-badge">
                <ShieldCheck size={12} aria-hidden="true" />
                Verified
              </span>
            </div>
          </div>

          <ul className="divide-y divide-border">
            {findings.map((finding) => (
              <li key={finding.path} className="flex gap-3 px-4 py-4 sm:px-5">
                <span className={`sev-pill h-fit shrink-0 ${finding.className}`}>
                  {finding.severity}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <code className="break-all font-mono text-[11px] text-foreground/85 sm:text-xs">
                      {finding.path}:{finding.line}
                    </code>
                    <span className="text-[11px] text-muted-foreground">
                      line {finding.line}
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                    {finding.detail}
                  </p>
                </div>
              </li>
            ))}
          </ul>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-3 text-[11px] text-muted-foreground sm:px-5">
            <span className="inline-flex items-center gap-1.5">
              <CheckCircle2 size={13} className="text-[var(--success)]" aria-hidden="true" />
              3 findings · 1 verified fix
            </span>
            <span className="font-mono">repository-aware</span>
          </div>
        </article>
      </Reveal>
    </section>
  );
}

export function LandingFaq() {
  return (
    <section
      id="faq"
      aria-labelledby="faq-title"
      className="mx-auto max-w-3xl scroll-mt-24 px-6 pb-24"
    >
      <Reveal>
        <div className="mb-8 space-y-3 text-center">
          <p className="text-xs font-semibold text-[var(--ember-ink)]">
            FAQ
          </p>
          <h2
            id="faq-title"
            className="text-3xl font-extrabold tracking-tight text-foreground md:text-4xl"
            style={{ fontFamily: 'var(--font-oxanium, inherit)' }}
          >
            Questions, answered
          </h2>
        </div>

        <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface-1/70">
          {faqs.map((item) => (
            <details key={item.question} className="faq-item group">
              <summary className="text-sm font-semibold text-foreground transition-colors hover:text-[var(--ember-ink)]">
                <span>{item.question}</span>
                <ChevronDown
                  size={17}
                  className="faq-chevron text-muted-foreground"
                  aria-hidden="true"
                />
              </summary>
              <p className="faq-answer text-sm leading-relaxed text-muted-foreground">
                {item.answer}
              </p>
            </details>
          ))}
        </div>
      </Reveal>
    </section>
  );
}

export function FinalCtaBand() {
  return (
    <section aria-labelledby="final-cta-title" className="mx-auto max-w-5xl px-6 pb-24">
      <Reveal>
        <div className="final-cta rounded-2xl px-6 py-12 text-center sm:py-14">
          <p className="text-xs font-semibold text-[var(--ember-ink)]">
            Open source, bring your own key
          </p>
          <h2
            id="final-cta-title"
            className="mt-3 text-3xl font-extrabold tracking-tight text-foreground md:text-4xl"
            style={{ fontFamily: 'var(--font-oxanium, inherit)' }}
          >
            Ship PRs you can trust.
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground md:text-base">
            Install Revora-PR and get a repository-aware review on your next pull request.
          </p>
          <a
            href={REVORA.github.app}
            target="_blank"
            rel="noopener noreferrer"
            className="cta-primary mt-7"
          >
            Install Revora-PR
            <ArrowRight size={16} aria-hidden="true" />
          </a>
          <p className="mt-4 text-xs text-muted-foreground">
            Free · Open source · 2-minute setup
          </p>
        </div>
      </Reveal>
    </section>
  );
}
