/**
 * Per-chat generation identity and delta buffering for the chat stream.
 *
 * Several chats may generate at once, so identity is scoped to one chat: a
 * token can only mutate its own chat's message, a stale token can never end a
 * newer generation of the same chat, and stopping one chat leaves every other
 * chat streaming. Each generation owns its own delta buffer, so concurrent
 * streams cannot mix text into the same animation frame.
 */

export interface StreamToken {
  readonly id: number;
  readonly chatId: string;
  readonly messageId: string;
  readonly controller: AbortController;
  readonly buffer: DeltaBuffer;
}

export interface StreamRegistry {
  /** Start a generation for one chat, superseding that chat's previous one. */
  begin: (chatId: string, messageId: string, controller?: AbortController) => StreamToken;
  /** The live generation of one chat, if any. */
  get: (chatId: string) => StreamToken | null;
  /** The most recently started live generation (any chat). */
  active: () => StreamToken | null;
  /** True only while the token still owns its chat's slot. */
  isCurrent: (token: StreamToken | null) => boolean;
  /** Clear the token, but only while it still owns its chat. */
  end: (token: StreamToken | null) => boolean;
  /** Abort one chat's generation (tab close, clear, invalid auth). */
  abort: (chatId: string) => StreamToken | null;
  /** Abort every generation (logout). */
  abortAll: () => StreamToken[];
  /** Chats that currently generate, in start order. */
  chatIds: () => string[];
  /** Every live token, in start order. */
  tokens: () => StreamToken[];
}

export function createStreamRegistry(): StreamRegistry {
  const live = new Map<string, StreamToken>();
  let nextId = 1;

  const latest = (): StreamToken | null => {
    let token: StreamToken | null = null;
    for (const item of live.values()) token = item;
    return token;
  };

  const drop = (chatId: string): StreamToken | null => {
    const token = live.get(chatId) ?? null;
    if (token) live.delete(chatId);
    return token;
  };

  return {
    begin(chatId, messageId, controller = new AbortController()) {
      const previous = drop(chatId);
      if (previous) previous.controller.abort();
      const token: StreamToken = {
        id: nextId,
        chatId,
        messageId,
        controller,
        buffer: createDeltaBuffer(),
      };
      nextId += 1;
      live.set(chatId, token);
      return token;
    },
    get: (chatId) => live.get(chatId) ?? null,
    active: latest,
    isCurrent: (token) => !!token && live.get(token.chatId) === token,
    end(token) {
      if (!token || live.get(token.chatId) !== token) return false;
      live.delete(token.chatId);
      return true;
    },
    abort(chatId) {
      const token = drop(chatId);
      token?.controller.abort();
      return token;
    },
    abortAll() {
      const tokens = [...live.values()];
      live.clear();
      for (const token of tokens) token.controller.abort();
      return tokens;
    },
    chatIds: () => [...live.keys()],
    tokens: () => [...live.values()],
  };
}

export interface DeltaBuffer {
  /** Accumulate streamed text until the next paint. */
  push: (delta: string) => void;
  /** Return everything buffered and clear it. */
  flush: () => string;
  peek: () => string;
  clear: () => void;
  pending: () => boolean;
}

/**
 * One buffer per generation. Text is applied once per animation frame instead
 * of once per token, and the buffer is flushed before a terminal status so the
 * final word is never lost.
 */
export function createDeltaBuffer(): DeltaBuffer {
  let buffered = '';
  return {
    push(delta) {
      if (delta) buffered += delta;
    },
    flush() {
      const text = buffered;
      buffered = '';
      return text;
    },
    peek: () => buffered,
    clear() {
      buffered = '';
    },
    pending: () => buffered.length > 0,
  };
}