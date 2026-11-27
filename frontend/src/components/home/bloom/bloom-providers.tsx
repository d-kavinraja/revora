'use client';

import { CloudLightning } from 'lucide-react';
import {
  Claude,
  Cohere,
  DeepSeek,
  Gemini,
  Grok,
  Groq,
  Mistral,
  Nvidia,
  Ollama,
  OpenAI,
  OpenRouter,
} from '@lobehub/icons';

/**
 * GitHub integration plus every AI provider Revora ships with: the shared
 * brand marks already used by the app's provider/settings UI, the bundled
 * kLLM emblem, and a cloud glyph for the managed kLLM Cloud provider.
 * The first five entries are the logos the landing page already showed.
 */
const LOGOS = [
  { label: 'GitHub', icon: <GithubGlyph /> },
  { label: 'OpenAI', icon: <OpenAI /> },
  { label: 'Claude', icon: <Claude.Color /> },
  { label: 'Google Gemini', icon: <Gemini.Color /> },
  { label: 'Groq', icon: <Groq /> },
  { label: 'DeepSeek', icon: <DeepSeek.Color /> },
  { label: 'OpenRouter', icon: <OpenRouter /> },
  { label: 'Cohere', icon: <Cohere.Color /> },
  { label: 'Mistral AI', icon: <Mistral.Color /> },
  { label: 'NVIDIA NIM', icon: <Nvidia.Color /> },
  { label: 'Grok', icon: <Grok /> },
  { label: 'Ollama', icon: <Ollama /> },
  { label: 'Ollama Cloud', icon: <Ollama /> },
  /* eslint-disable-next-line @next/next/no-img-element -- bundled brand asset */
  { label: 'kLLM', icon: <img src="/assets/kllm.svg" alt="" width={22} height={22} /> },
  { label: 'kLLM Cloud', icon: <CloudLightning /> },
] as const;

function GithubGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 .5C5.73.5.9 5.33.9 11.6c0 4.9 3.17 9.05 7.58 10.53.55.1.76-.24.76-.53v-1.87c-3.08.68-3.73-1.29-3.73-1.29-.51-1.29-1.24-1.63-1.24-1.63-1.01-.69.08-.68.08-.68 1.12.08 1.71 1.15 1.71 1.15 1 1.72 2.63 1.22 3.27.94.1-.73.39-1.24.71-1.52-2.46-.28-5.05-1.23-5.07-5.48 0-1.21.43-2.21 1.14-2.99-.11-.28-.49-1.41.11-2.94 0 0 .93-.3 3.05 1.15a10.5 10.5 0 0 1 5.55 0c2.12-1.45 3.05-1.15 3.05-1.15.6 1.53.22 2.66.11 2.94.71.78 1.14 1.78 1.14 2.99 0 4.26-2.6 5.19-5.07 5.47.4.35.76 1.03.76 2.08v3.09c0 .3.2.65.77.53A11.1 11.1 0 0 0 23.1 11.6C23.1 5.33 18.27.5 12 .5Z" />
    </svg>
  );
}

function ProviderGroup({ duplicate = false }: { duplicate?: boolean }) {
  return (
    <ul
      className="providers-group"
      aria-hidden={duplicate ? true : undefined}
      aria-label={duplicate ? undefined : 'Supported AI providers and integrations'}
    >
      {LOGOS.map((logo) => (
        <li
          className="logo-item"
          key={`${logo.label}-${duplicate ? 'dup' : 'main'}`}
          title={logo.label}
        >
          {logo.icon}
          <span>{logo.label}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Two identical groups in a `max-content` track: translating by exactly -50%
 * lands on the start of the copy, so the slow drift loops without a seam.
 */
export function BloomProviders() {
  return (
    <div className="providers">
      <div className="providers-track">
        <ProviderGroup />
        <ProviderGroup duplicate />
      </div>
    </div>
  );
}
