'use client';

import { useMemo, type RefObject } from 'react';
import type { ChatMessage, ResponseMetrics } from '@/lib/chat-state';
import ChatActivityIndicator from '@/components/chat/chat-activity-indicator';
import { MessageBubble } from './message-bubble';

interface ChatMessageListProps {
  messages: ChatMessage[];
  metrics?: Record<string, ResponseMetrics>;
  activeStreamMessageId?: string | null;
  thinking?: boolean;
  /**
   * Provider-neutral, already-mapped activity label produced by
   * `chat-activity.ts`. When null/empty the indicator renders nothing at all
   * (e.g. once content starts streaming). Never names a provider.
   */
  activityLabel?: string | null;
  thinkingOrbRef?: RefObject<HTMLDivElement | null>;
  canEdit?: boolean;
  canRegenerate?: boolean;
  editingMessageId?: string | null;
  onRetry?: (messageId: string) => void;
  onRegenerate?: (message: ChatMessage) => void;
  onBeginEdit?: (messageId: string) => void;
  onCancelEdit?: () => void;
  onEdit?: (messageId: string, content: string) => void;
}

export function ChatMessageList({
  messages,
  metrics,
  activeStreamMessageId,
  thinking = false,
  activityLabel,
  thinkingOrbRef,
  canEdit = false,
  canRegenerate = false,
  editingMessageId,
  onRetry,
  onRegenerate,
  onBeginEdit,
  onCancelEdit,
  onEdit,
}: ChatMessageListProps) {
  const rendered = useMemo(() => messages.map((message) => {
    const isPlaceholder = message.role === 'assistant'
      && message.id === activeStreamMessageId
      && !message.content?.trim();
    if (isPlaceholder && thinking) {
      // The compact pill lives in the same column as MessageBubble so the
      // existing layout shift is reduced compared to the previous 132 px
      // centered orb. The shell still auto-scrolls the ref into view.
      return (
        <div
          key={message.id}
          ref={thinkingOrbRef}
          className="flex flex-col items-start gap-2 py-3"
        >
          <ChatActivityIndicator label={activityLabel} />
        </div>
      );
    }
    if (isPlaceholder) return null;
    return (
      <MessageBubble
        key={message.id}
        message={message}
        metrics={metrics?.[message.id]}
        onRetry={
          message.status === 'error' || message.status === 'truncated' || message.status === 'aborted'
            ? () => onRetry?.(message.id)
            : undefined
        }
        onRegenerate={
          message.role === 'assistant' && message.status !== 'streaming' && onRegenerate
            ? () => onRegenerate(message)
            : undefined
        }
        canRegenerate={canRegenerate}
        editing={message.role === 'user' && editingMessageId === message.id}
        canEdit={canEdit}
        onBeginEdit={onBeginEdit}
        onCancelEdit={onCancelEdit}
        onEdit={onEdit}
      />
    );
  }), [
    canEdit,
    canRegenerate,
    editingMessageId,
    activeStreamMessageId,
    thinking,
    activityLabel,
    thinkingOrbRef,
    messages,
    metrics,
    onBeginEdit,
    onCancelEdit,
    onEdit,
    onRegenerate,
    onRetry,
  ]);

  // min-w-0/max-w-full: flex children default to min-width:auto, so a wide
  // Markdown table could otherwise push this column (and the whole chat UI)
  // wider than the mobile viewport. Tables scroll inside their own container
  // in MessageBubble; these guards keep the column locked to the screen width.
  return <div className="mx-auto flex w-full min-w-0 max-w-full max-w-3xl flex-col gap-8 pb-4">{rendered}</div>;
}
