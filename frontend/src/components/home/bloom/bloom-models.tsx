'use client';

import Link from 'next/link';

import { REVORA } from '@/lib/site';
import { ASSETS } from './assets';
import { Split } from './bloom-split';

const BYOK_PROVIDERS = [
  'Gemini',
  'Groq',
  'Cohere',
  'OpenRouter',
  'NVIDIA NIM',
  'OpenAI',
  'Anthropic',
] as const;

export function BloomModels() {
  return (
    <section className="models" id="models">
      <div className="sq-field" data-count="14" aria-hidden="true" />

      <div className="models-cloud" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element -- remote CloudFront watercolor asset */}
        <img className="drift-a" src={ASSETS.CLOUD_A} alt="" />
        <div className="glass" style={{ left: '14%', top: '26%', width: '15%' }} />
        <div className="glass" style={{ left: '40%', top: '56%', width: '13%' }} />
        <div className="glass" style={{ left: '62%', top: '20%', width: '12%' }} />
      </div>

      <div className="section-head">
        <span className="pill reveal">Open-source stack</span>
        <Split className="h2 split">Models for every deployment.</Split>
      </div>

      <div className="models-grid">
        <article className="model-card">
          <span className="glass model-glass" aria-hidden="true" />
          <span className="pill">Managed</span>
          <h3>Hosted models, no key required.</h3>
          <p>
            kLLM Cloud starts from <code>qwen3.8-27b</code> and includes Qwen-Coder and
            Mixtral-8x22B swarm variants. Hosted Ollama covers instant chat. No API key
            setup — available when enabled by your deployment.
          </p>
          <ul className="model-list" aria-label="Hosted model families">
            <li>Qwen3.8</li>
            <li>Qwen-Coder</li>
            <li>Mixtral-8x22B</li>
            <li>Hosted Ollama</li>
          </ul>
          <Link className="model-action" href="/chat">
            Try Chat →
          </Link>
        </article>

        <article className="model-card">
          <span className="glass model-glass" aria-hidden="true" />
          <span className="pill">Private</span>
          <h3>Your hardware, your code.</h3>
          <p>
            Run local kLLM or your own Ollama instance and keep proprietary source on your
            hardware. Loopback needs no gateway key; non-loopback deployments can add an
            optional server-side key.
          </p>
          <ul className="model-list" aria-label="Self-hosted options">
            <li>Local kLLM</li>
            <li>Local Ollama</li>
            <li>Optional gateway key</li>
          </ul>
          <Link className="model-action" href="/settings/kllm">
            Configure kLLM →
          </Link>
        </article>

        <article className="model-card">
          <span className="glass model-glass" aria-hidden="true" />
          <span className="pill">Bring your own key</span>
          <h3>Choose the model per repository.</h3>
          <p>
            Connect your own provider keys and route models per repository from Settings.
            Model Lab is where you explore Revora&apos;s own trained models, free during the
            beta trial.
          </p>
          <ul className="model-list" aria-label="Bring-your-own-key providers">
            {BYOK_PROVIDERS.map((provider) => (
              <li key={provider}>{provider}</li>
            ))}
          </ul>
          <Link className="model-action" href="/settings/routing">
            Route models →
          </Link>
        </article>
      </div>

      <div className="models-actions">
        <Link href="/model-lab">Explore Model Lab →</Link>
        <Link href="/chat">Try Chat →</Link>
        <a href={REVORA.github.repo} target="_blank" rel="noopener noreferrer">
          View Source on GitHub ↗
        </a>
      </div>
    </section>
  );
}
