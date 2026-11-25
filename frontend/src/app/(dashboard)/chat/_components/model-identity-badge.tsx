'use client';

import { ModelIcon } from '@/components/ui/model-icon';
import { managementLabelForModel, modelDisplayName, type ModelIdentity } from '@/lib/chat-state';

export function ModelIdentityBadge({ model }: { model: ModelIdentity | null }) {
  if (!model) return null;
  const management = managementLabelForModel(model);
  return (
    <span
      className="chat-ink hidden min-w-0 max-w-[240px] items-center gap-1.5 rounded-full border border-border/70 bg-surface-2/70 px-2 py-0.5 text-[11px] leading-none md:inline-flex lg:max-w-[300px]"
      title={`${modelDisplayName(model)} · ${management}`}
    >
      <ModelIcon model={model} size={14} className="shrink-0" />
      <span className="min-w-0 truncate font-medium">{modelDisplayName(model)}</span>
      <span aria-hidden className="shrink-0 text-muted-foreground/50">·</span>
      <span className="shrink-0 text-[10px] text-muted-foreground">{management}</span>
    </span>
  );
}
