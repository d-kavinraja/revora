import { ProviderIcon } from '@/components/ui/provider-icon';

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Claude',
  azure_openai: 'Azure OpenAI',
  cohere: 'Cohere',
  deepseek: 'DeepSeek',
  gemini: 'Google Gemini',
  groq: 'Groq',
  mistral: 'Mistral AI',
  nvidia: 'NVIDIA NIM',
  nvidia_nim: 'NVIDIA NIM',
  ollama: 'Ollama',
  ollama_cloud: 'Ollama Cloud',
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
};

const KNOWN_PROVIDERS = new Set(Object.keys(PROVIDER_LABELS));

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
  return KNOWN_PROVIDERS.has((slug ?? '').trim().toLowerCase());
}

const MARK_SIZES = {
  sm: 'h-7 w-7 rounded-md',
  md: 'h-8 w-8 rounded-lg',
  lg: 'h-10 w-10 rounded-lg',
} as const;

const ICON_SIZES = {
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
