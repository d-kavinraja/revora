// Safety ceiling only. Actual usable input is bounded by the selected model/gateway
// context window and backend request validation. Do not treat this as a product limit.
export const CHAT_MAX_MESSAGE_CHARS = 200_000;
export const CHAT_MAX_CONTEXT_MESSAGES = 20;
export const CHAT_MAX_CONTEXT_CHARS = 240_000;
export const CHAT_MAX_CHATS = 20;
export const CHAT_MAX_MESSAGES_PER_CHAT = 200;

export const TRUNCATION_MESSAGE =
  'The response stopped at the generation limit. Try regenerating or shortening your question.';

// Only known truncation/abnormal reasons are surfaced as failures. Unknown
// finish reasons are deliberately treated as a normal completion.
const TRUNCATION_FINISH_REASONS = new Set([
  'length',
  'max_tokens',
  'model_length',
  'content_filter',
  'loop_cut',
]);

export function isTruncatedFinish(reason?: string | null): boolean {
  return !!reason && TRUNCATION_FINISH_REASONS.has(reason.toLowerCase());
}

export type ResponsePhase =
  | 'preparing'
  | 'thinking'
  | 'generating'
  | 'complete'
  | 'stopped'
  | 'error'
  | 'truncated';

export interface ResponseMetrics {
  phase: ResponsePhase;
  startedAt: number;
  endedAt?: number;
  outputTokens?: number;
  promptTokens?: number;
  cachedTokens?: number;
  genTps?: number;
  genMs?: number;
  promptMs?: number;
  progress?: { cache: number; processed: number; total: number };
  contextUsed?: number;
  contextTotal?: number;
  model?: string;
}

/** Native kLLM formula: (processed - cache) / (total - cache) * 100. */
export function computePrefillPercent(
  progress?: { cache: number; processed: number; total: number } | null,
): number | null {
  if (!progress) return null;
  const { cache, processed, total } = progress;
  if (![cache, processed, total].every((v) => typeof v === 'number' && Number.isFinite(v))) return null;
  if (processed < cache || processed > total) return null;
  const denominator = total - cache;
  if (!(denominator > 0)) return null;
  const percent = Math.round(((processed - cache) / denominator) * 100);
  return Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : null;
}

/** Derived from llama-server timings, the same calculation the native UI uses. */
export function computeTokensPerSecond(tokens?: number, ms?: number): number | null {
  if (typeof tokens !== 'number' || typeof ms !== 'number') return null;
  if (!Number.isFinite(tokens) || !Number.isFinite(ms)) return null;
  if (!(tokens > 0) || !(ms > 0)) return null;
  const tps = (tokens / ms) * 1000;
  return Number.isFinite(tps) ? tps : null;
}

/** prompt_n and cache_n are distinct in llama-server; gen_n is output. */
export function computeContextUsed(timings?: {
  prompt_n?: number;
  cache_n?: number;
  gen_n?: number;
} | null): number | null {
  if (!timings) return null;
  const values = [timings.prompt_n, timings.cache_n, timings.gen_n];
  const valid = values.filter((v) => typeof v === 'number' && Number.isFinite(v) && v >= 0);
  return valid.length ? valid.reduce<number>((sum, v) => sum + (v as number), 0) : null;
}

/** Coalesce per-token telemetry into a single patch for the next paint. */
export function coalesceMetricsPatch(
  pending: { messageId: string; patch: Partial<ResponseMetrics> } | null,
  messageId: string,
  patch: Partial<ResponseMetrics>,
): { messageId: string; patch: Partial<ResponseMetrics> } {
  return {
    messageId,
    patch: pending && pending.messageId === messageId
      ? { ...pending.patch, ...patch }
      : patch,
  };
}

export type ChatRole = 'user' | 'assistant';
export type MessageStatus = 'complete' | 'streaming' | 'error' | 'stopped';

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  status: MessageStatus;
  error?: string;
  createdAt: number;
}

export interface TemporaryChat {
  id: string;
  title: string;
  model: string | null;
  messages: ChatMessage[];
  createdAt: number;
  updatedAt: number;
}

export interface ChatStoreStateShape {
  chats: Record<string, TemporaryChat>;
  order: string[];
  activeId: string | null;
}

function fallbackId(): string {
  return `chat_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

export function newId(prefix = 'id'): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${fallbackId()}`;
}

export function createMessage(
  role: ChatRole,
  content: string,
  status: MessageStatus = role === 'user' ? 'complete' : 'streaming',
  now = Date.now(),
): ChatMessage {
  return {
    id: newId('msg'),
    role,
    content,
    status,
    createdAt: now,
  };
}

/** Rebuild a turn for regeneration without duplicating the user message. */
export function buildRetryMessages(
  messages: ChatMessage[],
  assistantMessageId: string,
): { messages: ChatMessage[]; content: string; assistantMessageId: string } | null {
  const idx = messages.findIndex((m) => m.id === assistantMessageId);
  if (idx <= 0) return null;
  let userId = -1;
  for (let i = idx - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (msg.role === 'user' && msg.content.trim()) {
      userId = i;
      break;
    }
  }
  if (userId < 0) return null;
  const content = messages[userId].content;
  const assistant = createMessage('assistant', '', 'streaming');
  return {
    messages: [...messages.slice(0, userId + 1), assistant],
    content,
    assistantMessageId: assistant.id,
  };
}

export function deriveTitle(text: string): string {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (!normalized) return 'New chat';
  return normalized.length > 48 ? `${normalized.slice(0, 48).trimEnd()}…` : normalized;
}

export function createChat(model: string | null = null, now = Date.now()): TemporaryChat {
  return {
    id: newId('chat'),
    title: 'New chat',
    model,
    messages: [],
    createdAt: now,
    updatedAt: now,
  };
}

export function createInitialChatState(now = Date.now()): ChatStoreStateShape {
  const chat = createChat(null, now);
  return {
    chats: { [chat.id]: chat },
    order: [chat.id],
    activeId: chat.id,
  };
}

export function getActiveChat(state: ChatStoreStateShape): TemporaryChat | null {
  if (!state.activeId) return null;
  return state.chats[state.activeId] ?? null;
}

export function upsertChatOrder(order: string[], chatId: string): string[] {
  return [chatId, ...order.filter((id) => id !== chatId)];
}

export function buildChatContext(
  chat: TemporaryChat | null | undefined,
  options?: { maxMessages?: number; maxChars?: number },
): Array<{ role: ChatRole; content: string }> {
  if (!chat) return [];
  const maxMessages = options?.maxMessages ?? CHAT_MAX_CONTEXT_MESSAGES;
  const maxChars = options?.maxChars ?? CHAT_MAX_CONTEXT_CHARS;

  const eligible = chat.messages
    .filter(
      (m) =>
        m.status === 'complete' &&
        typeof m.content === 'string' &&
        m.content.trim().length > 0,
    )
    .map((m) => ({ role: m.role, content: m.content.trim() }));

  let selected = eligible.slice(-maxMessages);
  while (selected.length > 0 && selected[selected.length - 1].role !== 'user') {
    selected.pop();
  }

  let totalChars = selected.reduce((sum, m) => sum + m.content.length, 0);
  while (selected.length > 1 && totalChars > maxChars) {
    const removed = selected.shift();
    if (removed) totalChars -= removed.content.length;
  }

  while (selected.length > 0 && selected[0].role !== 'user') {
    selected.shift();
  }
  while (selected.length > 0 && selected[selected.length - 1].role !== 'user') {
    selected.pop();
  }

  if (selected.length === 1 && selected[0].content.length > maxChars) {
    selected = [
      {
        ...selected[0],
        content: selected[0].content.slice(-maxChars),
      },
    ];
  }

  return selected;
}

export interface KllmModelLike {
  key: string;
  status?: string;
  loaded?: boolean;
  ready?: boolean;
  readiness?: string;
  reason_code?: string;
  context_window?: number | null;
  vision?: boolean;
}

export interface GroupedModels {
  ready: KllmModelLike[];
  loading: KllmModelLike[];
  unloaded: KllmModelLike[];
  failed: KllmModelLike[];
  unavailable: KllmModelLike[];
}

export function isModelSelectable(model: KllmModelLike | null | undefined): boolean {
  return !!model && model.ready === true && model.readiness === 'ready';
}

export function groupModels(models: KllmModelLike[] | null | undefined): GroupedModels {
  const groups: GroupedModels = {
    ready: [],
    loading: [],
    unloaded: [],
    failed: [],
    unavailable: [],
  };
  for (const model of models ?? []) {
    if (isModelSelectable(model)) {
      groups.ready.push(model);
    } else if (model.readiness === 'loading' || model.status === 'loading') {
      groups.loading.push(model);
    } else if (model.readiness === 'failed' || model.status === 'failed') {
      groups.failed.push(model);
    } else if (model.readiness === 'unloaded' || model.status === 'unloaded') {
      groups.unloaded.push(model);
    } else {
      groups.unavailable.push(model);
    }
  }
  return groups;
}

export function pickDefaultModel(
  models: KllmModelLike[] | null | undefined,
  selected: string | null | undefined,
): string | null {
  const ready = (models ?? []).filter(isModelSelectable);
  if (ready.length === 0) return null;
  if (selected && ready.some((m) => m.key === selected)) return selected;
  return ready[0].key;
}
