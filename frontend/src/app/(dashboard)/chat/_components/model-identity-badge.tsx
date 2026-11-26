'use client';

import { ModelIcon } from '@/components/ui/model-icon';
import {
  KLLM_IDENTITY_LABEL,
  KLLM_PROVIDER,
  managementLabelForModel,
  modelDisplayName,
  modelProviderSlug,
  type ModelIdentity,
} from '@/lib/chat-state';

export function ModelIdentityBadge({ model }: { model: ModelIdentity | null }) {
  if (!model) return null;
  const displayName = modelDisplayName(model);
  const management = managementLabelForModel(model);
  // Compact mobile form drops the "Managed by" prefix; wording stays consistent.
  const compactManagement = management.replace(/^Managed by /, '');
  // kLLM identity + management attribution, e.g. for the accessible title.
  const isKllm = modelProviderSlug(model) === KLLM_PROVIDER;
  const title = isKllm
    ? `${KLLM_IDENTITY_LABEL} · ${displayName}`
    : `${displayName} · ${management}`;

  return (
    <span
      className="chat-ink inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-border/70 bg-surface-2/70 px-2 py-1 text-[11px] leading-none sm:max-w-[240px] lg:max-w-[300px]"
      title={title}
    >
      <ModelIcon model={model} size={14} className="shrink-0" />
      <span className="min-w-[3ch] shrink truncate font-medium">{displayName}</span>
      <span aria-hidden className="shrink-0 text-muted-foreground/50">·</span>
      <span className="shrink-0 whitespace-nowrap text-[10px] text-muted-foreground sm:hidden">{compactManagement}</span>
      <span className="hidden shrink-0 whitespace-nowrap text-[10px] text-muted-foreground sm:inline">{management}</span>
    </span>
  );
}
