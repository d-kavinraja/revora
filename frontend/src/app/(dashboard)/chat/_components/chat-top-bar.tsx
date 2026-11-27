'use client';

import type { ReactNode } from 'react';
import { RefreshCwIcon } from 'lucide-react';

import type { ContextMeter, ModelIdentity } from '@/lib/chat-state';
import { useChatKeyboard } from '@/lib/use-chat-keyboard';
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
  /** Mode-specific action: chat delete in Temporary, nothing in Persistent. */
  rightSlot?: ReactNode;
  /** Chat tabs plus the new-chat button — the entire second mobile row. */
  sessionSlot?: ReactNode;
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
  sessionSlot,
}: ChatTopBarProps) {
  const keyboardOpen = useChatKeyboard();

  return (
    <div className="w-full shrink-0 relative z-30 border-b border-border/60 bg-background/85 backdrop-blur-md">
      <div className="px-4 py-2 md:flex-row md:items-center md:justify-between md:px-6 md:py-2.5">
        {/* Row 1 — mode selector and status/action controls. */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <div className="hidden min-w-0 shrink md:block">{title}</div>
            {onModeChange ? (
              <ChatModeSwitch
                activeMode={activeMode}
                temporaryEnabled={temporaryEnabled}
                persistentEnabled={persistentEnabled}
                onSelect={onModeChange}
              />
            ) : (
              <span className="chat-ink hidden text-xs md:inline">
                {activeMode === 'temporary' ? 'Temporary' : 'Persistent'}
              </span>
            )}
            <div className="hidden min-w-0 md:flex">
              <ModelIdentityBadge model={model} />
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <ChatContextUsage
              contextInfo={contextInfo}
              open={contextOpen}
              onOpenChange={onContextOpenChange}
            />
            {rightSlot}
            <button
              type="button"
              onClick={onRefreshModels}
              className="chat-ink inline-flex h-10 min-h-8 w-10 min-w-8 shrink-0 items-center justify-center rounded-lg border border-border/60 transition hover:bg-muted/60 hover:text-foreground md:h-8 md:w-8"
              aria-label="Refresh models"
              title="Refresh models"
            >
              <RefreshCwIcon size={14} />
            </button>
          </div>
        </div>

        {/* Row 2 — chats only; collapses automatically when the keyboard opens. */}
        <div
          aria-hidden={keyboardOpen}
          className={`overflow-hidden transition-[max-height,opacity] duration-200 ease-in-out motion-reduce:transition-none md:hidden ${
            keyboardOpen
              ? 'pointer-events-none max-h-0 opacity-0'
              : 'max-h-14 opacity-100'
          }`}
        >
          <div className="flex min-w-0 items-center justify-between gap-2 pt-2">
            {sessionSlot}
          </div>
        </div>
      </div>
    </div>
  );
}
