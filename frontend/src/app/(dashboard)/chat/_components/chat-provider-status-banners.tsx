'use client';

import type { ChatCatalog, ChatCatalogProvider } from '@/lib/api';
import { HOSTED_PROVIDER, KLLM_PROVIDER } from '@/lib/chat-state';

function providerBannerText(providerId: string, provider: ChatCatalogProvider): string | null {
  const label = providerId === HOSTED_PROVIDER ? 'Hosted Models' : 'kLLM';
  if (!provider.enabled) return null;
  if (provider.waking) return 'Starting hosted models… This can take a moment.';
  if (!provider.configured) return `${label} are not configured on this server.`;
  if (!provider.reachable) return `${label} are unreachable right now.`;
  if (provider.stale) return `${label} status is stale. Refresh before sending.`;
  if (provider.discovery_ok === false) return `Checking ${label.toLowerCase()} readiness…`;
  return null;
}

export function ChatProviderStatusBanners({ catalog }: { catalog: ChatCatalog | null | undefined }) {
  if (!catalog) return null;

  const providers = catalog.providers ?? [];
  const enabledProviders = providers.filter((p) => p.enabled);

  if (enabledProviders.length === 0) {
    return (
      <div className="mx-auto mb-4 max-w-3xl rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning dark:bg-zinc-950/80 dark:border-amber-400/35 dark:text-amber-200 dark:backdrop-blur-md">
        No AI models are available. Ask an administrator to enable a provider.
      </div>
    );
  }

  const banners = [HOSTED_PROVIDER, KLLM_PROVIDER]
    .map((providerId) => {
      const provider = providers.find((p) => p.provider === providerId);
      if (!provider) return null;
      const text = providerBannerText(providerId, provider);
      if (!text) return null;
      const isWaking = provider.waking;
      return (
        <div
          key={providerId}
          className={
            isWaking
              ? 'mx-auto mb-4 max-w-3xl rounded-xl border border-brand/30 bg-brand/10 px-3 py-2 text-sm text-foreground'
              : 'mx-auto mb-4 max-w-3xl rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning dark:bg-zinc-950/80 dark:border-amber-400/35 dark:text-amber-200 dark:backdrop-blur-md'
          }
        >
          {text}
        </div>
      );
    })
    .filter(Boolean);

  return banners.length > 0 ? <>{banners}</> : null;
}
