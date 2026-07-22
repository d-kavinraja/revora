import { GlobeIcon } from 'lucide-react';
import {
  Gemini,
  OpenAI,
  Claude,
  DeepSeek,
  Groq,
  OpenRouter,
  Azure,
  Ollama,
  Cohere,
  Mistral,
} from '@lobehub/icons';

export function ProviderIcon({ slug, size = 24, className = '' }: { slug?: string; size?: number; className?: string }) {
  const normSlug = (slug || '').toLowerCase();
  switch (normSlug) {
    case 'gemini': return <Gemini.Color size={size} className={className} />;
    case 'openai': return <OpenAI size={size} className={className} />;
    case 'anthropic': return <Claude.Color size={size} className={className} />;
    case 'deepseek': return <DeepSeek.Color size={size} className={className} />;
    case 'groq': return <Groq size={size} className={className} />;
    case 'openrouter': return <OpenRouter size={size} className={className} />;
    case 'azure': return <Azure.Color size={size} className={className} />;
    case 'ollama': return <Ollama size={size} className={className} />;
    case 'cohere': return <Cohere.Color size={size} className={className} />;
    case 'mistral': return <Mistral.Color size={size} className={className} />;
    default: return <GlobeIcon size={size} className={`text-muted-foreground ${className}`} />;
  }
}
