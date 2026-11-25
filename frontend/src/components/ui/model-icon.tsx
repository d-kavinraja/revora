'use client';

import { DeepSeek, Gemma, HuggingFace, Meta, Microsoft, Mistral, Qwen } from '@lobehub/icons';

import { ProviderIcon } from '@/components/ui/provider-icon';
import {
  modelFamily,
  modelProviderSlug,
  type ModelIdentity,
} from '@/lib/chat-state';

/**
 * One icon resolver for every surface that shows a model: the Chat dropdown,
 * composer trigger, header badge and response header, plus Admin model tables.
 * Family marks win when the model name is unambiguous; otherwise we fall back
 * to the provider icon used by the rest of the app.
 */
export function ModelIcon({
  model,
  size = 14,
  className = '',
}: {
  model?: ModelIdentity | null;
  size?: number;
  className?: string;
}) {
  switch (modelFamily(model)) {
    case 'meta':
      return <Meta.Color size={size} className={className} />;
    case 'qwen':
      return <Qwen.Color size={size} className={className} />;
    case 'gemma':
      return <Gemma.Color size={size} className={className} />;
    case 'mistral':
      return <Mistral.Color size={size} className={className} />;
    case 'deepseek':
      return <DeepSeek.Color size={size} className={className} />;
    case 'microsoft':
      return <Microsoft.Color size={size} className={className} />;
    case 'huggingface':
      return <HuggingFace.Color size={size} className={className} />;
    default:
      return <ProviderIcon slug={modelProviderSlug(model)} size={size} className={className} />;
  }
}
