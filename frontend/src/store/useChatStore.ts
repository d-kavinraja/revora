import { create } from 'zustand';

import { useAuthStore } from '@/store/useAuthStore';
import {
  CHAT_MAX_CHATS,
  createChat,
  createEmptyChatState,
  createInitialChatState,
  deriveTitle,
  planRegeneration as planRegenerationFor,
  providerForKey,
  type ChatMessage,
  type ChatStoreStateShape,
  type EditPlan,
  type MessageStatus,
  type RegenerationPlan,
  type TemporaryChat,
} from '@/lib/chat-state';
import {
  appendDelta,
  applyEditPlan as applyEditPlanInCore,
  applyRegenerationPlan,
  finalizeAssistant,
  reserveTurn,
  restoreSnapshot,
  setConfirmedModel as setConfirmedModelIn,
  type MutationResult,
  type Provenance,
} from '@/lib/chat-store-core';

export type BeginTurnResult =
  | { ok: true; userMessageId: string; assistantMessageId: string }
  | { ok: false; reason: 'chat_missing' | 'empty' | 'chat_full'; remaining: number };

interface ChatActions {
  ensureActiveChat: () => void;
  createNewChat: (model?: string | null) => string;
  selectChat: (id: string) => void;
  deleteChat: (id: string) => void;
  clearChat: (id: string) => void;
  setChatModel: (id: string, model: string | null) => void;
  /**
   * Append a user turn and its assistant placeholder together. Refused when the
   * chat has fewer than two slots left, so a prompt is never orphaned at the
   * message limit.
   */
  beginTurn: (id: string, content: string, provenance?: Provenance) => BeginTurnResult;
  appendAssistantDelta: (chatId: string, messageId: string, delta: string) => void;
  finishAssistantMessage: (
    chatId: string,
    messageId: string,
    status: Exclude<MessageStatus, 'streaming'>,
    error?: string,
    finishReason?: string | null,
  ) => void;
  /** Record the model id confirmed by the provider for one assistant turn. */
  setConfirmedModel: (chatId: string, messageId: string, upstreamModel: string | null) => void;
  /**
   * Plan a regeneration without changing state: the caller can confirm the
   * exact number of discarded turns before applying it.
   */
  planRegeneration: (
    chatId: string,
    assistantMessageId: string,
    provenance?: Provenance,
  ) => RegenerationPlan | null;
  /**
   * Apply a planned regeneration. Refused when the conversation moved on since
   * the plan was made, so a late callback can never rewrite newer history.
   */
  applyRegeneration: (chatId: string, plan: RegenerationPlan) => boolean;
  /**
   * Apply a planned user-message edit. The user turn is replaced in place and
   * every later turn is discarded; stale plans are refused.
   */
  applyMessageEdit: (chatId: string, plan: EditPlan) => boolean;
  /**
   * Restore a previously captured message list exactly (undo). The snapshot must
   * describe finished turns and the current tail must still be the generation
   * being undone.
   */
  restoreMessages: (
    chatId: string,
    messages: ChatMessage[],
    expectedTailId?: string | null,
  ) => boolean;
  /** Unsent composer text for one chat. Memory only: never persisted. */
  setDraft: (chatId: string, value: string) => void;
  clearDraft: (chatId: string) => void;
  /** Mirror the live generation of one chat (assistant message id). */
  markStreaming: (chatId: string, messageId: string) => void;
  /** Clear a stream marker, but only while it still names that message. */
  clearStreaming: (chatId: string, messageId?: string) => void;
  resetAll: () => void;
}

export type ChatStore = ChatStoreStateShape & ChatActions;

function upsertOrder(order: string[], chatId: string): string[] {
  return [chatId, ...order.filter((id) => id !== chatId)];
}

function touch(chat: TemporaryChat, now = Date.now()): TemporaryChat {
  return { ...chat, updatedAt: now };
}

function applyMutation(
  set: (partial: Partial<ChatStore>) => void,
  state: ChatStore,
  chatId: string,
  result: MutationResult,
): boolean {
  if (!result.ok) return false;
  const chat = state.chats[chatId];
  if (!chat) return false;
  set({
    chats: {
      ...state.chats,
      [chatId]: { ...chat, messages: result.messages, updatedAt: Date.now() },
    },
  });
  return true;
}

export const useChatStore = create<ChatStore>()((set, get) => ({
  ...createEmptyChatState(),

  ensureActiveChat: () => {
    const state = get();
    if (state.activeId && state.chats[state.activeId]) return;
    const initial = createInitialChatState();
    set(initial);
  },

  createNewChat: (model = null) => {
    const state = get();
    if (state.order.length >= CHAT_MAX_CHATS) {
      return state.activeId ?? state.order[0];
    }
    const chat = createChat(model);
    set({
      chats: { ...state.chats, [chat.id]: chat },
      order: upsertOrder(state.order, chat.id),
      activeId: chat.id,
    });
    return chat.id;
  },

  selectChat: (id) => {
    const state = get();
    if (!state.chats[id]) return;
    set({ activeId: id });
  },

  deleteChat: (id) => {
    const state = get();
    if (!state.chats[id]) return;
    const chats = { ...state.chats };
    delete chats[id];
    const order = state.order.filter((x) => x !== id);
    let activeId = state.activeId === id ? order[0] ?? null : state.activeId;
    if (!activeId || !chats[activeId]) {
      const created = createChat(null);
      chats[created.id] = created;
      order.unshift(created.id);
      activeId = created.id;
    }
    const drafts = { ...state.drafts };
    const streaming = { ...state.streaming };
    delete drafts[id];
    delete streaming[id];
    set({ chats, order, activeId, drafts, streaming });
  },

  clearChat: (id) => {
    const state = get();
    const chat = state.chats[id];
    if (!chat) return;
    const drafts = { ...state.drafts };
    const streaming = { ...state.streaming };
    delete drafts[id];
    delete streaming[id];
    set({
      chats: {
        ...state.chats,
        [id]: {
          ...chat,
          title: 'New chat',
          messages: [],
          updatedAt: Date.now(),
        },
      },
      drafts,
      streaming,
    });
  },

  setChatModel: (id, model) => {
    const state = get();
    const chat = state.chats[id];
    if (!chat) return;
    // Selection only: existing turns keep the model they were generated with.
    set({ chats: { ...state.chats, [id]: touch({ ...chat, model }) } });
  },

  beginTurn: (id, content, provenance) => {
    const state = get();
    const chat = state.chats[id];
    if (!chat) return { ok: false, reason: 'chat_missing', remaining: 0 };
    const attribution: Provenance | undefined = provenance ?? {
      model: chat.model,
      provider: chat.model ? providerForKey(chat.model) : null,
    };
    const result = reserveTurn(chat.messages, content, attribution);
    if (!result.ok) {
      return { ok: false, reason: result.reason, remaining: result.remaining };
    }
    const title = chat.messages.length === 0 ? deriveTitle(content) : chat.title;
    set({
      chats: {
        ...state.chats,
        [id]: {
          ...chat,
          title,
          messages: result.messages,
          updatedAt: Date.now(),
        },
      },
      order: upsertOrder(state.order, id),
    });
    return {
      ok: true,
      userMessageId: result.userMessageId,
      assistantMessageId: result.assistantMessageId,
    };
  },

  appendAssistantDelta: (chatId, messageId, delta) => {
    const state = get();
    const chat = state.chats[chatId];
    if (!chat) return;
    const messages = appendDelta(chat.messages, messageId, delta);
    if (!messages) return;
    set({
      chats: {
        ...state.chats,
        [chatId]: { ...chat, messages, updatedAt: Date.now() },
      },
    });
  },

  finishAssistantMessage: (chatId, messageId, status, error, finishReason) => {
    const state = get();
    const chat = state.chats[chatId];
    if (!chat) return;
    // Idempotent: a late stream event can never overwrite an already-final
    // status (aborted -> complete) or resurrect a stale generation.
    const messages = finalizeAssistant(chat.messages, messageId, status, error, finishReason);
    if (!messages) return;
    set({
      chats: {
        ...state.chats,
        [chatId]: { ...chat, messages, updatedAt: Date.now() },
      },
    });
  },

  setConfirmedModel: (chatId, messageId, upstreamModel) => {
    const state = get();
    const chat = state.chats[chatId];
    if (!chat) return;
    const messages = setConfirmedModelIn(chat.messages, messageId, upstreamModel);
    if (!messages) return;
    set({
      chats: {
        ...state.chats,
        [chatId]: { ...chat, messages, updatedAt: Date.now() },
      },
    });
  },

  planRegeneration: (chatId, assistantMessageId, provenance) => {
    const chat = get().chats[chatId];
    if (!chat) return null;
    const attribution: Provenance = provenance ?? {
      model: chat.model,
      provider: chat.model ? providerForKey(chat.model) : null,
    };
    return planRegenerationFor(chat.messages, assistantMessageId, attribution);
  },

  applyRegeneration: (chatId, plan) => {
    const state = get();
    const chat = state.chats[chatId];
    if (!chat) return false;
    // The placeholder carries the model selected for this regeneration, not the
    // one that produced the turn being replaced.
    const result = applyRegenerationPlan(chat.messages, plan, {
      model: chat.model,
      provider: chat.model ? providerForKey(chat.model) : null,
    });
    return applyMutation(set, state, chatId, result);
  },

  applyMessageEdit: (chatId, plan) => {
    const state = get();
    const chat = state.chats[chatId];
    if (!chat) return false;
    // The new answer is generated by the model selected now, not by whichever
    // model produced the original turn being edited.
    const result = applyEditPlanInCore(chat.messages, plan, {
      model: chat.model,
      provider: chat.model ? providerForKey(chat.model) : null,
    });
    return applyMutation(set, state, chatId, result);
  },

  restoreMessages: (chatId, messages, expectedTailId) => {
    const state = get();
    const chat = state.chats[chatId];
    if (!chat) return false;
    const result = restoreSnapshot(chat.messages, messages, expectedTailId);
    return applyMutation(set, state, chatId, result);
  },

  setDraft: (chatId, value) => {
    const state = get();
    if (!state.chats[chatId] || state.drafts[chatId] === value) return;
    const drafts = { ...state.drafts };
    if (value) drafts[chatId] = value;
    else delete drafts[chatId];
    set({ drafts });
  },

  clearDraft: (chatId) => {
    const state = get();
    if (state.drafts[chatId] === undefined) return;
    const drafts = { ...state.drafts };
    delete drafts[chatId];
    set({ drafts });
  },

  markStreaming: (chatId, messageId) => {
    const state = get();
    if (!state.chats[chatId] || state.streaming[chatId] === messageId) return;
    set({ streaming: { ...state.streaming, [chatId]: messageId } });
  },

  clearStreaming: (chatId, messageId) => {
    const state = get();
    const current = state.streaming[chatId];
    if (current === undefined) return;
    if (messageId && current !== messageId) return;
    const streaming = { ...state.streaming };
    delete streaming[chatId];
    set({ streaming });
  },

  resetAll: () => set(createEmptyChatState()),
}));

useAuthStore.subscribe((state, prev) => {
  const userChanged = prev.user?.id !== state.user?.id;
  const loggedOut = prev.isAuthenticated && !state.isAuthenticated;
  if (userChanged || loggedOut) {
    useChatStore.getState().resetAll();
  }
});

export const selectActiveChat = (state: ChatStore) =>
  (state.activeId ? state.chats[state.activeId] : null) ?? null;
