'use client';

import { ModelIcon } from '@/components/ui/model-icon';
import {
  managementLabelForModel,
  modelDisplayName,
  providerSourceLabel,
  type ModelIdentity,
} from '@/lib/chat-state';

// Logo · model name · provider source · management. The name truncates first so
// the source and management attribution stay readable on narrow headers.
export function ModelIdentityBadge({ model }: { model: ModelIdentity | null }) {
  if (!model) return null;
  const displayName = modelDisplayName(model);
  const source = providerSourceLabel(model);
  const management = managementLabelForModel(model);
  // Compact mobile form drops the "Managed by" prefix; wording stays consistent.
  const compactManagement = management.replace(/^Managed by /, '');

  return (
    <span
      className="chat-ink inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-border/70 bg-surface-2/70 px-2 py-1 text-[11px] leading-none sm:max-w-[320px] lg:max-w-[400px]"
      title={`${displayName} · ${source} · ${management}`}
    >
      <ModelIcon model={model} size={14} className="shrink-0" />
      <span className="min-w-[3ch] shrink truncate font-medium">{displayName}</span>
      <span aria-hidden className="shrink-0 text-muted-foreground/50">·</span>
      <span className="shrink-0 whitespace-nowrap font-medium text-foreground/80">{source}</span>
      <span aria-hidden className="shrink-0 text-muted-foreground/50">·</span>
      <span className="shrink-0 whitespace-nowrap text-[10px] text-muted-foreground sm:hidden">{compactManagement}</span>
      <span className="hidden shrink-0 whitespace-nowrap text-[10px] text-muted-foreground sm:inline">{management}</span>
    </span>
  );
}
