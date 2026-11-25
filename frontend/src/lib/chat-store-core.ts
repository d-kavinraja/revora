import {
  CHAT_MAX_MESSAGES_PER_CHAT,
  createMessage,
  type ChatMessage,
  type ChatProviderId,
  type EditPlan,
  type MessageStatus,
  type RegenerationPlan,
} from './chat-state.ts';

/**
 * Pure conversation mutations shared by the store and its regression tests.
 * Nothing here touches React or the network: each helper receives the current
 * message list and returns the next one, or refuses with a reason. The store is
 * a thin wrapper, so the lifecycle guarantees are executable in Node.
 */

export type Provenance = {
  model?: string | null;
  provider?: ChatProviderId | null;
};

export type MutationResult =
  | { ok: true; messages: ChatMessage[] }
  | { ok: false; reason: MutationRefusal };

export type MutationRefusal =
  | 'chat_missing'
  | 'empty'
  | 'chat_full'
  | 'empty_plan'
  | 'stale_plan'
  | 'generating'
  | 'empty_snapshot'
  | 'snapshot_too_long'
  | 'invalid_snapshot'
  | 'stale_snapshot'
  | 'message_missing';

export type ReserveTurnResult =
  | {
      ok: true;
      messages: ChatMessage[];
      userMessageId: string;
      assistantMessageId: string;
    }
  | { ok: false; reason: 'empty' | 'chat_full'; remaining: number };

const VALID_ROLES = new Set(['user', 'assistant']);

/**
 * Reserve a user turn and its assistant placeholder atomically.
 *
 * Two slots are required, not one: appending the prompt when the placeholder
 * cannot fit leaves an orphaned question at the chat limit that can never be
 * answered. A refusal leaves the conversation untouched.
 */
export function reserveTurn(
  messages: readonly ChatMessage[],
  content: string,
  provenance?: Provenance,
  now = Date.now(),
): ReserveTurnResult {
  const trimmed = typeof content === 'string' ? content.trim() : '';
  const remaining = Math.max(0, CHAT_MAX_MESSAGES_PER_CHAT - messages.length);
  if (!trimmed) return { ok: false, reason: 'empty', remaining };
  if (remaining < 2) return { ok: false, reason: 'chat_full', remaining };
  const user = createMessage('user', trimmed, 'complete', now);
  const assistant = createMessage('assistant', '', 'streaming', now, provenance);
  return {
    ok: true,
    messages: [...messages, user, assistant],
    userMessageId: user.id,
    assistantMessageId: assistant.id,
  };
}

/**
 * Apply a previously planned regeneration. Refused as soon as the conversation
 * no longer matches the plan, so a late callback can never rewrite newer
 * history. The placeholder gets the provenance of the model actually used now,
 * never the one that produced the turn being replaced.
 */
export function applyRegenerationPlan(
  messages: readonly ChatMessage[],
  plan: RegenerationPlan,
  provenance?: Provenance,
): MutationResult {
  if (!plan.head.length) return { ok: false, reason: 'empty_plan' };
  if (messages.length !== plan.head.length + plan.replaced.length) {
    return { ok: false, reason: 'stale_plan' };
  }
  const headMatches = plan.head.every((m, i) => messages[i]?.id === m.id);
  const tailMatches = plan.replaced.every(
    (m, i) => messages[plan.head.length + i]?.id === m.id,
  );
  if (!headMatches || !tailMatches) return { ok: false, reason: 'stale_plan' };
  if (messages.some((m) => m.id === plan.assistantMessageId)) {
    return { ok: false, reason: 'stale_plan' };
  }
  if (messages.some((m) => m.status === 'streaming')) {
    return { ok: false, reason: 'generating' };
  }
  const next = plan.messages.map((message) => {
    if (message.id !== plan.assistantMessageId) return { ...message };
    return {
      ...message,
      model: provenance?.model ?? null,
      provider: provenance?.provider ?? null,
      // A fresh generation has no confirmed upstream model or reason yet.
      upstreamModel: null,
      finishReason: null,
    };
  });
  return { ok: true, messages: next };
}

/**
 * Apply a previously planned user-message edit. The user turn is replaced in
 * place and every later turn is discarded. A late callback can never rewrite
 * newer history: the plan is refused unless the current conversation still
 * matches it exactly.
 */
export function applyEditPlan(
  messages: readonly ChatMessage[],
  plan: EditPlan,
  provenance?: Provenance,
): MutationResult {
  if (!plan.edited?.id || !plan.content) return { ok: false, reason: 'empty_plan' };
  if (messages.length !== plan.head.length + 1 + plan.replaced.length) {
    return { ok: false, reason: 'stale_plan' };
  }
  const headMatches = plan.head.every((m, i) => messages[i]?.id === m.id);
  const currentEdited = messages[plan.head.length];
  const editedMatches =
    currentEdited?.id === plan.edited.id &&
    currentEdited.role === 'user' &&
    currentEdited.content === plan.originalContent &&
    plan.edited.content === plan.content;
  const tailMatches = plan.replaced.every(
    (m, i) => messages[plan.head.length + 1 + i]?.id === m.id,
  );
  if (!headMatches || !editedMatches || !tailMatches) {
    return { ok: false, reason: 'stale_plan' };
  }
  if (messages.some((m) => m.id === plan.assistantMessageId)) {
    return { ok: false, reason: 'stale_plan' };
  }
  if (messages.some((m) => m.status === 'streaming')) {
    return { ok: false, reason: 'generating' };
  }
  const next = plan.messages.map((message) => {
    if (message.id === plan.assistantMessageId) {
      return {
        ...message,
        model: provenance?.model ?? null,
        provider: provenance?.provider ?? null,
        upstreamModel: null,
        finishReason: null,
      };
    }
    return { ...message };
  });
  return { ok: true, messages: next };
}

/**
 * Restore an undo snapshot. Refused when the chat is generating, when the
 * snapshot is not a valid finished conversation, or when the current tail is no
 * longer the generation the snapshot is meant to undo (so undo can never
 * discard newer turns).
 */
export function restoreSnapshot(
  current: readonly ChatMessage[],
  snapshot: readonly ChatMessage[],
  expectedTailId?: string | null,
): MutationResult {
  if (!Array.isArray(snapshot) || snapshot.length === 0) {
    return { ok: false, reason: 'empty_snapshot' };
  }
  if (snapshot.length > CHAT_MAX_MESSAGES_PER_CHAT) {
    return { ok: false, reason: 'snapshot_too_long' };
  }
  if (current.some((m) => m.status === 'streaming')) {
    return { ok: false, reason: 'generating' };
  }
  if (expectedTailId && current[current.length - 1]?.id !== expectedTailId) {
    return { ok: false, reason: 'stale_snapshot' };
  }
  const seen = new Set<string>();
  const messages: ChatMessage[] = [];
  for (const item of snapshot) {
    if (!item || typeof item !== 'object') return { ok: false, reason: 'invalid_snapshot' };
    if (typeof item.id !== 'string' || !item.id) {
      return { ok: false, reason: 'invalid_snapshot' };
    }
    if (seen.has(item.id)) return { ok: false, reason: 'invalid_snapshot' };
    if (!VALID_ROLES.has(item.role)) return { ok: false, reason: 'invalid_snapshot' };
    if (typeof item.content !== 'string') return { ok: false, reason: 'invalid_snapshot' };
    if (!item.status || item.status === 'streaming') {
      return { ok: false, reason: 'invalid_snapshot' };
    }
    if (typeof item.createdAt !== 'number' || !Number.isFinite(item.createdAt)) {
      return { ok: false, reason: 'invalid_snapshot' };
    }
    seen.add(item.id);
    messages.push({ ...item });
  }
  return { ok: true, messages };
}

/** Append a streamed delta to the current placeholder only. */
export function appendDelta(
  messages: readonly ChatMessage[],
  messageId: string,
  delta: string,
): ChatMessage[] | null {
  if (!delta) return null;
  const index = messages.findIndex((m) => m.id === messageId);
  if (index < 0) return null;
  const message = messages[index];
  if (message.role !== 'assistant' || message.status !== 'streaming') return null;
  const next = messages.slice();
  next[index] = { ...message, content: message.content + delta };
  return next;
}

/**
 * Finalize the streaming placeholder exactly once. A late event from a stopped
 * or replaced stream can never overwrite an already-final status.
 */
export function finalizeAssistant(
  messages: readonly ChatMessage[],
  messageId: string,
  status: Exclude<MessageStatus, 'streaming'>,
  error?: string,
  finishReason?: string | null,
): ChatMessage[] | null {
  const index = messages.findIndex((m) => m.id === messageId);
  if (index < 0) return null;
  const message = messages[index];
  if (message.role !== 'assistant' || message.status !== 'streaming') return null;
  const next = messages.slice();
  next[index] = {
    ...message,
    status,
    error: error || undefined,
    finishReason: finishReason ?? null,
  };
  return next;
}

/**
 * Record the model id the provider confirmed for this turn. Only the provider's
 * own model event calls this; a key, a guess or a fallback never does.
 */
export function setConfirmedModel(
  messages: readonly ChatMessage[],
  messageId: string,
  upstreamModel: string | null,
): ChatMessage[] | null {
  const index = messages.findIndex((m) => m.id === messageId);
  if (index < 0) return null;
  const message = messages[index];
  if (message.role !== 'assistant') return null;
  const next = messages.slice();
  next[index] = { ...message, upstreamModel: upstreamModel?.trim() || null };
  return next;
}
