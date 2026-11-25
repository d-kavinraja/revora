'use client';

import { useMemo, type RefObject } from 'react';
import type { ChatMessage, ResponseMetrics } from '@/lib/chat-state';
import ThinkingOrb from '@/components/ui/ai-thiking-orb-and-input';
import { MessageBubble } from './message-bubble';

interface ChatMessageListProps {
  messages: ChatMessage[];
  metrics?: Record<string, ResponseMetrics>;
  activeStreamMessageId?: string | null;
  thinking?: boolean;
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
      return (
        <div key={message.id} ref={thinkingOrbRef} className="py-8 flex flex-col items-center justify-center">
          <ThinkingOrb active={thinking} size={132} />
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
    thinkingOrbRef,
    messages,
    metrics,
    onBeginEdit,
    onCancelEdit,
    onEdit,
    onRegenerate,
    onRetry,
  ]);

  return <div className="mx-auto flex max-w-3xl flex-col gap-8 pb-4">{rendered}</div>;
}
