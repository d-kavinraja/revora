import { create } from 'zustand';

import { useAuthStore } from '@/store/useAuthStore';
import {
  buildRetryMessages,
  CHAT_MAX_CHATS,
  CHAT_MAX_MESSAGES_PER_CHAT,
  buildChatContext,
  createChat,
  createInitialChatState,
  createMessage,
  deriveTitle,
  type ChatStoreStateShape,
  type MessageStatus,
  type TemporaryChat,
} from '@/lib/chat-state';

interface ChatActions {
  ensureActiveChat: () => void;
  createNewChat: (model?: string | null) => string;
  selectChat: (id: string) => void;
  deleteChat: (id: string) => void;
  clearChat: (id: string) => void;
  setChatModel: (id: string, model: string | null) => void;
  appendUserMessage: (id: string, content: string) => string | null;
  startAssistantMessage: (id: string) => string | null;
  appendAssistantDelta: (chatId: string, messageId: string, delta: string) => void;
  finishAssistantMessage: (
    chatId: string,
    messageId: string,
    status: Exclude<MessageStatus, 'streaming'>,
    error?: string,
  ) => void;
  /** Reuse an existing user turn: drop the failed assistant message and append a fresh placeholder. */
  prepareRetry: (
    chatId: string,
    assistantMessageId: string,
  ) => { content: string; assistantMessageId: string } | null;
  resetAll: () => void;
}

export type ChatStore = ChatStoreStateShape & ChatActions;

function upsertOrder(order: string[], chatId: string): string[] {
  return [chatId, ...order.filter((id) => id !== chatId)];
}

function touch(chat: TemporaryChat, now = Date.now()): TemporaryChat {
  return { ...chat, updatedAt: now };
}

export const useChatStore = create<ChatStore>()((set, get) => ({
  ...createInitialChatState(),

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
    set({ chats, order, activeId });
  },

  clearChat: (id) => {
    const state = get();
    const chat = state.chats[id];
    if (!chat) return;
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
    });
  },

  setChatModel: (id, model) => {
    const state = get();
    const chat = state.chats[id];
    if (!chat) return;
    set({ chats: { ...state.chats, [id]: touch({ ...chat, model }) } });
  },

  appendUserMessage: (id, content) => {
    const state = get();
    const chat = state.chats[id];
    if (!chat) return null;
    if (chat.messages.length >= CHAT_MAX_MESSAGES_PER_CHAT) return null;
    const message = createMessage('user', content, 'complete');
    const title = chat.messages.length === 0 ? deriveTitle(content) : chat.title;
    const updated: TemporaryChat = {
      ...chat,
      title,
      messages: [...chat.messages, message],
      updatedAt: Date.now(),
    };
    set({
      chats: { ...state.chats, [id]: updated },
      order: upsertOrder(state.order, id),
    });
    return message.id;
  },

  startAssistantMessage: (id) => {
    const state = get();
    const chat = state.chats[id];
    if (!chat) return null;
    if (chat.messages.length >= CHAT_MAX_MESSAGES_PER_CHAT) return null;
    const message = createMessage('assistant', '', 'streaming');
    const updated: TemporaryChat = {
      ...chat,
      messages: [...chat.messages, message],
      updatedAt: Date.now(),
    };
    set({
      chats: { ...state.chats, [id]: updated },
      order: upsertOrder(state.order, id),
    });
    return message.id;
  },

  appendAssistantDelta: (chatId, messageId, delta) => {
    if (!delta) return;
    const state = get();
    const chat = state.chats[chatId];
    if (!chat) return;
    const idx = chat.messages.findIndex((m) => m.id === messageId);
    if (idx < 0) return;
    const msg = chat.messages[idx];
    if (msg.role !== 'assistant' || msg.status !== 'streaming') return;
    const messages = chat.messages.slice();
    messages[idx] = { ...msg, content: msg.content + delta };
    set({
      chats: {
        ...state.chats,
        [chatId]: { ...chat, messages, updatedAt: Date.now() },
      },
    });
  },

  finishAssistantMessage: (chatId, messageId, status, error) => {
    const state = get();
    const chat = state.chats[chatId];
    if (!chat) return;
    const idx = chat.messages.findIndex((m) => m.id === messageId);
    if (idx < 0) return;
    const msg = chat.messages[idx];
    if (msg.role !== 'assistant') return;
    const messages = chat.messages.slice();
    messages[idx] = { ...msg, status, error: error || undefined };
    set({
      chats: {
        ...state.chats,
        [chatId]: { ...chat, messages, updatedAt: Date.now() },
      },
    });
  },

  prepareRetry: (chatId, assistantMessageId) => {
    const state = get();
    const chat = state.chats[chatId];
    if (!chat) return null;
    const prepared = buildRetryMessages(chat.messages, assistantMessageId);
    if (!prepared) return null;
    set({
      chats: {
        ...state.chats,
        [chatId]: { ...chat, messages: prepared.messages, updatedAt: Date.now() },
      },
    });
    return { content: prepared.content, assistantMessageId: prepared.assistantMessageId };
  },

  resetAll: () => set(createInitialChatState()),
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

export const selectChatContext = (state: ChatStore, chatId: string) =>
  buildChatContext(state.chats[chatId]);
