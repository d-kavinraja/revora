'use client';

import type { ReactNode } from 'react';
import { RefreshCwIcon } from 'lucide-react';

import type { ContextMeter, ModelIdentity } from '@/lib/chat-state';
import { ChatContextUsage } from './chat-context-usage';
import { ChatModeSwitch } from './chat-mode-switch';
import { ModelIdentityBadge } from './model-identity-badge';

interface ChatTopBarProps {
  title: ReactNode;
  activeMode: 'temporary' | 'persistent';
  temporaryEnabled: boolean;
  persistentEnabled: boolean;
  onModeChange?: (mode: 'temporary' | 'persistent') => void;
  model: ModelIdentity | null;
  contextInfo: ContextMeter;
  contextOpen: boolean;
  onContextOpenChange: (open: boolean) => void;
  onRefreshModels: () => void;
  rightSlot?: ReactNode;
}

export function ChatTopBar({
  title,
  activeMode,
  temporaryEnabled,
  persistentEnabled,
  onModeChange,
  model,
  contextInfo,
  contextOpen,
  onContextOpenChange,
  onRefreshModels,
  rightSlot,
}: ChatTopBarProps) {
  return (
    <div className="w-full shrink-0 relative z-30 border-b border-border/60 bg-background/85 py-2.5 backdrop-blur-md">
      <div className="flex w-full items-center justify-between gap-3 px-4 md:px-6">
        <div className="min-w-0 flex items-center gap-2">
          <div className="min-w-0 shrink">{title}</div>
          {onModeChange ? (
            <ChatModeSwitch
              activeMode={activeMode}
              temporaryEnabled={temporaryEnabled}
              persistentEnabled={persistentEnabled}
              onSelect={onModeChange}
            />
          ) : (
            <span className="chat-ink hidden text-xs sm:inline">
              {activeMode === 'temporary' ? 'Temporary' : 'Persistent'}
            </span>
          )}
          <ModelIdentityBadge model={model} />
        </div>

        <div className="flex items-center gap-1.5">
          <ChatContextUsage
            contextInfo={contextInfo}
            open={contextOpen}
            onOpenChange={onContextOpenChange}
          />
          {rightSlot}
          <button
            type="button"
            onClick={onRefreshModels}
            className="chat-ink inline-flex h-8 w-8 items-center justify-center rounded-md transition hover:bg-muted/60 hover:text-foreground"
            aria-label="Refresh model status"
            title="Refresh model status"
          >
            <RefreshCwIcon size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
