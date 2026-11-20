import { ProviderIcon } from '@/components/ui/provider-icon';

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Claude',
  azure: 'Azure OpenAI',
  azure_openai: 'Azure OpenAI',
  claude: 'Claude',
  cohere: 'Cohere',
  deepseek: 'DeepSeek',
  gemini: 'Google Gemini',
  google: 'Google Gemini',
  google_gemini: 'Google Gemini',
  grok: 'Grok',
  groq: 'Groq',
  kllm: 'kLLM',
  mistral: 'Mistral AI',
  mistralai: 'Mistral AI',
  nvidia: 'NVIDIA NIM',
  nvidia_nim: 'NVIDIA NIM',
  ollama: 'Ollama',
  ollama_cloud: 'Ollama Cloud',
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
  xai: 'Grok',
  'x-ai': 'Grok',
};

const PROVIDER_ALIASES: Record<string, string> = {
  azure: 'azure_openai',
  claude: 'anthropic',
  google: 'gemini',
  google_gemini: 'gemini',
  mistralai: 'mistral',
  'x-ai': 'grok',
  xai: 'grok',
};

const KNOWN_PROVIDERS = new Set(Object.keys(PROVIDER_LABELS));

function normalizeProviderSlug(slug?: string | null): string {
  const normalized = (slug ?? '').trim().toLowerCase();
  return PROVIDER_ALIASES[normalized] ?? normalized;
}

const MODEL_PROVIDER_FAMILIES: ReadonlyArray<readonly [RegExp, string]> = [
  [/^claude(?:[-_.:]|$)/, 'anthropic'],
  [
    /^(?:gpt-(?!oss(?:[-_.:]|$))|o[1-9](?:[-_.:]|$)|chatgpt(?:[-_.:]|$)|text-embedding-|dall-e-)/,
    'openai',
  ],
  [/^gemini(?:[-_.:]|$)/, 'gemini'],
  [/^deepseek(?:[-_.:]|$)/, 'deepseek'],
  [
    /^(?:mistral|mixtral|codestral|ministral|pixtral|devstral|magistral)(?:[-_.:]|$)/,
    'mistral',
  ],
  [/^(?:command|embed-english|embed-multilingual|rerank)(?:[-_.:]|$)/, 'cohere'],
  [/^grok(?:[-_.:]|$)/, 'grok'],
];

/**
 * Resolve a provider from a model identifier only when the identifier makes
 * the provider family unambiguous. Ambiguous models (for example a hosted
 * Llama variant) intentionally return null instead of guessing.
 */
export function providerFromModel(model?: string | null): string | null {
  const normalized = (model ?? '').trim().toLowerCase();
  if (!normalized) return null;

  const slashIndex = normalized.indexOf('/');
  if (slashIndex > 0) {
    const prefix = normalizeProviderSlug(normalized.slice(0, slashIndex));
    if (KNOWN_PROVIDERS.has(prefix)) return prefix;
  }

  for (const [pattern, provider] of MODEL_PROVIDER_FAMILIES) {
    if (pattern.test(normalized)) return provider;
  }

  return null;
}

function humanizeSlug(slug: string): string {
  return slug
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function providerDisplayName(
  slug?: string | null,
  label?: string | null,
): string {
  const normalized = (slug ?? '').trim().toLowerCase();
  const cleanLabel = (label ?? '').trim();

  // Managed server-owned provider: always display as plain "kLLM", regardless
  // of any legacy/label suffix returned by the backend.
  if (normalized === 'kllm') return 'kLLM';
  if (cleanLabel && cleanLabel.toLowerCase() !== normalized) return cleanLabel;
  if (normalized && PROVIDER_LABELS[normalized]) {
    return PROVIDER_LABELS[normalized];
  }
  if (normalized) return humanizeSlug(normalized);
  return cleanLabel || 'Unknown provider';
}

export function providerInitials(
  slug?: string | null,
  label?: string | null,
): string {
  const display = providerDisplayName(slug, label);
  const words = display.split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0].charAt(0)}${words[1].charAt(0)}`.toUpperCase();
}

export function isKnownProvider(slug?: string | null): boolean {
  return KNOWN_PROVIDERS.has(normalizeProviderSlug(slug));
}

const MARK_SIZES = {
  xs: 'h-[22px] w-[22px] rounded-md',
  sm: 'h-7 w-7 rounded-md',
  md: 'h-8 w-8 rounded-lg',
  lg: 'h-10 w-10 rounded-lg',
} as const;

const ICON_SIZES = {
  xs: 18,
  sm: 15,
  md: 17,
  lg: 21,
} as const;

export function ProviderMark({
  slug,
  label,
  size = 'md',
  className = '',
}: {
  slug?: string | null;
  label?: string | null;
  size?: keyof typeof MARK_SIZES;
  className?: string;
}) {
  const display = providerDisplayName(slug, label);

  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center border border-border bg-surface-2 text-muted-foreground ${MARK_SIZES[size]} ${className}`}
      aria-hidden="true"
      title={display}
    >
      {isKnownProvider(slug) ? (
        <ProviderIcon slug={slug ?? undefined} size={ICON_SIZES[size]} />
      ) : (
        <span className="admin-figure text-[10px] font-semibold tracking-[0.02em]">
          {providerInitials(slug, label)}
        </span>
      )}
    </span>
  );
}

export function ProviderBadge({
  slug,
  label,
  size = 'md',
  className = '',
  muted = false,
}: {
  slug?: string | null;
  label?: string | null;
  size?: keyof typeof MARK_SIZES;
  className?: string;
  muted?: boolean;
}) {
  const display = providerDisplayName(slug, label);

  return (
    <span className={`inline-flex min-w-0 items-center gap-2 ${className}`}>
      <ProviderMark slug={slug} label={label} size={size} />
      <span
        className={`min-w-0 truncate text-sm font-medium ${
          muted ? 'text-muted-foreground' : 'text-foreground'
        }`}
        title={display}
      >
        {display}
      </span>
    </span>
  );
}

export function ProviderText({
  slug,
  label,
  className = '',
}: {
  slug?: string | null;
  label?: string | null;
  className?: string;
}) {
  return (
    <span className={className} title={providerDisplayName(slug, label)}>
      {providerDisplayName(slug, label)}
    </span>
  );
}
