import Image from 'next/image';

import { GlobeIcon } from 'lucide-react';
import {
  Azure,
  Gemini,
  OpenAI,
  Claude,
  DeepSeek,
  Grok,
  Groq,
  OpenRouter,
  Ollama,
  Cohere,
  Mistral,
  Nvidia,
} from '@lobehub/icons';
import { cn } from '@/lib/utils';

export function ProviderIcon({ slug, size = 24, className = '' }: { slug?: string; size?: number; className?: string }) {
  const normSlug = (slug ?? '').trim().toLowerCase();
  switch (normSlug) {
    case 'gemini':
    case 'google':
    case 'google_gemini':
      return <Gemini.Color size={size} className={className} />;
    case 'openai':
      // OpenAI's mark is intentionally monochrome: black on light, white on dark.
      return <OpenAI size={size} className={cn('text-foreground', className)} />;
    case 'anthropic':
    case 'claude':
      return <Claude.Color size={size} className={className} />;
    case 'deepseek':
      return <DeepSeek.Color size={size} className={className} />;
    case 'groq':
      return <Groq size={size} className={cn('text-[#F55036]', className)} />;
    case 'openrouter':
      return <OpenRouter size={size} className={cn('text-[#6566F1]', className)} />;
    case 'ollama':
    case 'ollama_cloud':
      // Ollama's mark is monochrome and follows the surrounding theme.
      return <Ollama size={size} className={cn('text-foreground', className)} />;
    case 'cohere':
      return <Cohere.Color size={size} className={className} />;
    case 'mistral':
    case 'mistralai':
      return <Mistral.Color size={size} className={className} />;
    case 'nvidia':
    case 'nvidia_nim':
      return <Nvidia.Color size={size} className={className} />;
    case 'grok':
    case 'xai':
    case 'x-ai':
      // Grok/xAI's mark is monochrome and follows the surrounding theme.
      return <Grok size={size} className={cn('text-foreground', className)} />;
    case 'azure':
    case 'azure_openai':
      return <Azure.Color size={size} className={className} />;
    case 'kllm':
      // Official kLLM logo (served from /assets/kllm.svg).
      return (
        <Image
          src="/assets/kllm.svg"
          alt=""
          width={size}
          height={size}
          className={cn('inline-flex rounded-md', className)}
        />
      );
    default:
      return <GlobeIcon size={size} className={cn('text-muted-foreground', className)} />;
  }
}
