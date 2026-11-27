// Safety ceiling only. Actual usable input is bounded by the selected model/gateway
// context window and backend request validation. Do not treat this as a product limit.
export const CHAT_MAX_MESSAGE_CHARS = 200_000;
// Fixed fallbacks, used only when the selected model window is unknown. They
// mirror backend/app/services/chat_service.py.
export const CHAT_MAX_CONTEXT_MESSAGES = 20;
export const CHAT_MAX_CONTEXT_CHARS = 240_000;
// Provider-independent conversation ceilings: one history never exceeds these.
export const CHAT_CONTEXT_MESSAGES_GLOBAL = 200;
export const CHAT_CONTEXT_CHARS_GLOBAL = 1_200_000;
export const CHAT_MAX_CHATS = 20;
export const CHAT_MAX_MESSAGES_PER_CHAT = 200;

// Fitting constants, identical to the backend so the advisory preview matches
// what the server will actually send.
export const CHARS_PER_TOKEN_FIT = 3;
export const CONTEXT_OUTPUT_RESERVE_TOKENS = 2_048;
export const MIN_CONTEXT_OUTPUT_TOKENS = 1_024;
export const MAX_CONTEXT_OUTPUT_TOKENS = 16_384;
export const DEFAULT_CONTEXT_OUTPUT_TOKENS = 4_096;

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

/**
 * Reported when a stream ended without a terminal completion event. It is not
 * a provider reason: it means the connection closed before the model said it
 * was done, so the answer must not be presented as a clean completion.
 */
export const INCOMPLETE_FINISH_REASON = 'incomplete';

/** A missing or explicitly incomplete reason means the turn never finished. */
export function isIncompleteFinish(reason?: string | null): boolean {
  const normalized = reason?.trim().toLowerCase() ?? '';
  return normalized === '' || normalized === INCOMPLETE_FINISH_REASON;
}

/**
 * Map a provider finish reason onto the terminal message status. An absent
 * reason is never treated as success: only an explicit reason completes a turn.
 */
export function finalStatusFor(
  reason?: string | null,
): 'complete' | 'truncated' | 'aborted' {
  if (isIncompleteFinish(reason)) return 'aborted';
  return isTruncatedFinish(reason) ? 'truncated' : 'complete';
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
/** Canonical provider ids. Routing is derived from the model key only. */
export type ChatProviderId = 'kllm' | 'kllm-cloud' | 'hosted-ollama';
/**
 * `streaming` is the only non-terminal status. Every other status is final and
 * keeps whatever content the model (or the user) produced:
 * - complete: the model finished normally
 * - truncated: a generation limit or filter cut the response short
 * - stopped: the user stopped generation
 * - aborted: the page or stream went away before the response finished
 * - error: the request failed after the assistant turn was created
 */
export type MessageStatus = 'complete' | 'streaming' | 'error' | 'stopped' | 'truncated' | 'aborted';

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  status: MessageStatus;
  error?: string;
  createdAt: number;
  /**
   * Provenance for assistant turns only. `model` is the key requested for this
   * turn, recorded when the turn was created so switching the chat model later
   * never rewrites it. `upstreamModel` is set only from the provider's own model
   * event; it is never guessed. User turns carry no attribution at all.
   */
  model?: string | null;
  provider?: ChatProviderId | null;
  /**
   * Clean catalog name captured when the turn was created, e.g. "Qwen3.8 27B".
   * Optional: older turns without it fall back to the cleaned key.
   */
  displayName?: string | null;
  upstreamModel?: string | null;
  /** Provider finish reason, kept so status wording can name the real cause. */
  finishReason?: string | null;
}

export type MessageProvenance = Pick<
  ChatMessage,
  'model' | 'provider' | 'displayName' | 'upstreamModel'
>;

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
  /** Unsent composer text, keyed by chat id. In memory only, never persisted. */
  drafts: Record<string, string>;
  /** Assistant message currently generating per chat, for tab indicators. */
  streaming: Record<string, string>;
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
  provenance?: MessageProvenance,
): ChatMessage {
  return {
    id: newId('msg'),
    role,
    content,
    status,
    createdAt: now,
    ...(provenance ?? {}),
  };
}

/**
 * Describe a regeneration before it is applied. Planning is pure: the caller
 * can show the exact number of turns that will be discarded and abort without
 * touching the stored conversation. Regenerating a turn that is not the last
 * one necessarily discards every later message.
 */
export interface RegenerationPlan {
  /** Message list with the old assistant turn replaced by a streaming placeholder. */
  messages: ChatMessage[];
  /** Turns before the user prompt that produced the response (unchanged). */
  head: ChatMessage[];
  /** The old assistant turn and every later message, kept verbatim for undo. */
  replaced: ChatMessage[];
  /** Exact count of later messages lost if the plan is applied. */
  discardedCount: number;
  /** Whether the regenerated turn is currently the last message. */
  isLast: boolean;
  /** Full pre-regeneration list, restored by undo. */
  previous: ChatMessage[];
  /** The user prompt that is sent again (never duplicated). */
  content: string;
  userId: string;
  assistantMessageId: string;
}

export function planRegeneration(
  messages: ChatMessage[],
  assistantMessageId: string,
  provenance?: MessageProvenance,
): RegenerationPlan | null {
  const idx = messages.findIndex((m) => m.id === assistantMessageId);
  if (idx <= 0) return null;
  if (messages[idx].role !== 'assistant' || messages[idx].status === 'streaming') return null;
  let userId = -1;
  for (let i = idx - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (msg.role === 'user' && msg.content.trim()) {
      userId = i;
      break;
    }
  }
  if (userId < 0) return null;
  const assistant = createMessage('assistant', '', 'streaming', Date.now(), provenance);
  const head = messages.slice(0, userId + 1);
  return {
    messages: [...head, assistant],
    head,
    replaced: messages.slice(idx),
    discardedCount: messages.length - idx - 1,
    isLast: idx === messages.length - 1,
    previous: messages,
    content: messages[userId].content,
    userId: messages[userId].id,
    assistantMessageId: assistant.id,
  };
}

/** Backwards-compatible projection of {@link planRegeneration}. */
export function buildRetryMessages(
  messages: ChatMessage[],
  assistantMessageId: string,
): { messages: ChatMessage[]; content: string; assistantMessageId: string } | null {
  const plan = planRegeneration(messages, assistantMessageId);
  if (!plan) return null;
  return {
    messages: plan.messages,
    content: plan.content,
    assistantMessageId: plan.assistantMessageId,
  };
}

/**
 * Describe an edit to a previously sent user turn. Like regeneration, planning
 * is pure: nothing is written until the caller applies the plan. The user turn
 * is replaced in place (same id and createdAt) and every later turn is
 * discarded, so the history before the edit plus the new answer stays coherent.
 */
export interface EditPlan {
  /** Messages after the edit: head + edited user + streaming assistant placeholder. */
  messages: ChatMessage[];
  /** Turns before the edited user message, unchanged. */
  head: ChatMessage[];
  /** The edited user message, preserving its id and createdAt. */
  edited: ChatMessage;
  /** The old answer and every later turn, kept verbatim for undo. */
  replaced: ChatMessage[];
  /** The answer immediately after the edited user turn; it is regenerated, not a later turn. */
  replacedAnswer: ChatMessage | null;
  /** Turns after the replaced answer that are truly removed by the edit. */
  laterMessages: ChatMessage[];
  /** Exact number of later messages lost if the plan is applied. */
  discardedCount: number;
  /** Semantic later turns removed (one per later user prompt). */
  laterTurnCount: number;
  /** Whether the edit only replaces the current answer and removes no later turn. */
  isLast: boolean;
  /** Full pre-edit list, restored by undo. */
  previous: ChatMessage[];
  /** Trimmed replacement text. */
  content: string;
  /** Original text, used by the store to reject stale plans. */
  originalContent: string;
  userId: string;
  assistantMessageId: string;
}

export function planMessageEdit(
  messages: ChatMessage[],
  userId: string,
  nextContent: string,
  provenance?: MessageProvenance,
): EditPlan | null {
  const content = nextContent.trim();
  if (!content) return null;
  const idx = messages.findIndex((message) => message.id === userId);
  if (idx < 0) return null;
  const original = messages[idx];
  if (original.role !== 'user' || original.status === 'streaming') return null;

  const edited: ChatMessage = { ...original, content };
  const assistant = createMessage('assistant', '', 'streaming', Date.now(), provenance);
  const head = messages.slice(0, idx);
  const replaced = messages.slice(idx + 1);
  // The immediate answer belongs to the edited turn: it is regenerated, not a
  // "later turn". Everything after it is a later conversation turn and is
  // genuinely removed, so confirmation and undo wording count those instead.
  const replacedAnswer = replaced[0]?.role === 'assistant' ? replaced[0] : null;
  const laterMessages = replacedAnswer ? replaced.slice(1) : replaced;
  const laterUserTurns = laterMessages.reduce(
    (count, message) => count + (message.role === 'user' ? 1 : 0),
    0,
  );
  const laterTurnCount = laterMessages.length === 0 ? 0 : Math.max(1, laterUserTurns);
  return {
    messages: [...head, edited, assistant],
    head,
    edited,
    replaced,
    replacedAnswer,
    laterMessages,
    discardedCount: laterMessages.length,
    laterTurnCount,
    isLast: laterMessages.length === 0,
    previous: messages,
    content,
    originalContent: original.content,
    userId: original.id,
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

export function createEmptyChatState(): ChatStoreStateShape {
  return { chats: {}, order: [], activeId: null, drafts: {}, streaming: {} };
}

export function createInitialChatState(now = Date.now()): ChatStoreStateShape {
  const chat = createChat(null, now);
  return {
    chats: { [chat.id]: chat },
    order: [chat.id],
    activeId: chat.id,
    drafts: {},
    streaming: {},
  };
}

export function getActiveChat(state: ChatStoreStateShape): TemporaryChat | null {
  if (!state.activeId) return null;
  return state.chats[state.activeId] ?? null;
}

/** Include the unsent composer text when estimating the next outgoing prompt. */
export function withPendingChatDraft(
  chat: TemporaryChat | null | undefined,
  draft: string,
): TemporaryChat | null {
  if (!chat) return null;
  const content = draft.trim();
  if (!content) return chat;
  return {
    ...chat,
    messages: [
      ...chat.messages,
      {
        id: 'context-pending-draft',
        role: 'user',
        content,
        status: 'complete',
        createdAt: 0,
      },
    ],
  };
}

export function upsertChatOrder(order: string[], chatId: string): string[] {
  return [chatId, ...order.filter((id) => id !== chatId)];
}

/**
 * Markers are added to the outgoing copy only, never to the stored message, so
 * copying or undoing a turn shows exactly what the user saw. They tell the next
 * model that the previous turn ended early instead of implying it was complete,
 * and they keep the user's prompt and the partial answer in the same history.
 */
export const INCOMPLETE_MARKERS: Record<
  Exclude<MessageStatus, 'complete' | 'streaming'>,
  string
> = {
  truncated: '[response cut off by the generation limit]',
  stopped: '[response stopped before it finished]',
  aborted: '[response interrupted before it finished]',
  error: '[the response failed before it finished]',
};

/** Only the in-flight placeholder is excluded from the conversation history. */
export function isContextEligible(status: MessageStatus): boolean {
  return status !== 'streaming';
}

export function incompleteMarker(status: MessageStatus): string | null {
  if (status === 'complete' || status === 'streaming') return null;
  return INCOMPLETE_MARKERS[status];
}

export function applyIncompleteMarker(content: string, status: MessageStatus): string {
  const marker = incompleteMarker(status);
  if (!marker) return content;
  return content.endsWith(marker) ? content : `${content}\n\n${marker}`;
}

/**
 * Outbound-only marker for a turn that had to be clipped to the window. The
 * stored message is never modified, and clipping stays idempotent: a clipped
 * copy always carries exactly one marker, however often it is refitted.
 */
export const CONTEXT_CLIP_MARKER = '\n\n[... clipped to fit the model context ...]\n\n';
// Share of the room kept from the beginning; the rest keeps the end.
const CONTEXT_CLIP_HEAD_SHARE = 0.6;

export function isClippedContent(content: string): boolean {
  return content.includes(CONTEXT_CLIP_MARKER);
}

/**
 * Clip one oversized turn, keeping its beginning and its end. Keeping only the
 * tail silently dropped the instruction (the model answered an anonymous
 * excerpt); keeping only the head drops the end of a pasted trace the user is
 * asking about. The 60/40 split mirrors the backend exactly.
 */
export function clipMessageContent(content: string, maxChars: number): string {
  const limit = Number.isFinite(maxChars) ? Math.floor(maxChars) : 0;
  if (limit <= CONTEXT_CLIP_MARKER.length + 8) {
    // Too small for a marker: keep the instruction rather than nothing.
    return content.slice(0, Math.max(0, limit));
  }
  if (content.length <= limit) return content;
  const body = content.split(CONTEXT_CLIP_MARKER).join('\n');
  const room = Math.max(1, limit - CONTEXT_CLIP_MARKER.length);
  const headLength = Math.max(1, Math.floor(room * CONTEXT_CLIP_HEAD_SHARE));
  const tailLength = Math.max(0, room - headLength);
  const head = body.slice(0, headLength);
  const tail = tailLength > 0 ? body.slice(-tailLength) : '';
  return `${head}${CONTEXT_CLIP_MARKER}${tail}`;
}

/**
 * Model/provider attribution for one assistant bubble. The requested key is
 * always shown; when the provider confirmed a different upstream id, both are
 * shown instead of quietly replacing one with the other.
 */
export interface MessageAttribution {
  provider: ChatProviderId | null;
  requested: string | null;
  confirmed: string | null;
  /** Clean model name: the stored catalog name, else the cleaned key. */
  name: string | null;
  /** Readable provider source, e.g. "kLLM Cloud". Never a routing prefix. */
  source: string | null;
  /** Management attribution, e.g. "Managed by Revora". */
  management: string | null;
  /** `source · name`, with the requested key noted when the provider differs. */
  label: string | null;
  title: string | null;
}

export function messageAttribution(
  message: Pick<ChatMessage, 'role' | 'model' | 'provider' | 'displayName' | 'upstreamModel'>,
): MessageAttribution {
  const empty: MessageAttribution = {
    provider: null,
    requested: null,
    confirmed: null,
    name: null,
    source: null,
    management: null,
    label: null,
    title: null,
  };
  if (message.role !== 'assistant') return empty;
  const requested = message.model?.trim() || null;
  const provider = message.provider ?? (requested ? providerForKey(requested) : null);
  const confirmed = message.upstreamModel?.trim() || null;
  // Strip every accepted routing prefix, including the legacy hosted spelling,
  // so a stored key can never leak into the visible attribution.
  const bare = requested ? stripModelRoutingPrefix(requested) : null;
  const display = confirmed ?? bare;
  const identity: ModelIdentity = { key: requested, provider };
  const source = provider || requested ? providerSourceLabel(identity) : null;
  const management = source ? managementLabelForModel(identity) : null;
  if (!display) {
    return { provider, requested, confirmed, name: null, source, management, label: source, title: null };
  }
  const name = message.displayName?.trim() || display;
  const differs = !!(confirmed && bare && confirmed !== bare);
  const baseLabel = source ? `${source} · ${name}` : name;
  const title = [
    `Requested: ${requested ?? 'unknown'}`,
    `Confirmed by provider: ${confirmed ?? 'not reported'}`,
  ].join('\n');
  return {
    provider,
    requested,
    confirmed,
    name,
    source,
    management,
    label: differs ? `${baseLabel} (requested ${bare})` : baseLabel,
    title,
  };
}

/**
 * Explain a terminal status with the actual cause. A truncated answer and a
 * dropped connection must never share wording, and a missing terminal event is
 * reported as incomplete rather than as a clean finish.
 */
export function finishNotice(
  message: Pick<ChatMessage, 'status' | 'finishReason' | 'error'> & { content?: string },
): string | null {
  const reason = message.finishReason?.trim().toLowerCase() || null;
  switch (message.status) {
    case 'error':
      return message.error?.trim() || 'Response failed.';
    case 'truncated':
      return reason === 'content_filter'
        ? 'The provider\'s safety filter stopped this response.'
        : TRUNCATION_MESSAGE;
    case 'aborted':
      return reason === INCOMPLETE_FINISH_REASON
        ? 'The connection closed before the model reported completion, so this answer may be incomplete.'
        : 'Response interrupted before it finished.';
    case 'stopped':
      return 'Generation stopped before it finished.';
    default:
      return null;
  }
}

/** Wording for the undo bar. It never claims removals that did not happen. */
export function undoNotice(discarded: number): string {
  const count = Number.isFinite(discarded) ? Math.max(0, Math.floor(discarded)) : 0;
  if (count === 0) return 'Response regenerated. The previous answer can be restored.';
  if (count === 1) return 'Response regenerated. 1 later message was removed.';
  return `Response regenerated. ${count} later messages were removed.`;
}

/** Wording for the regeneration confirmation, with the exact removal count. */
export function regenerationPrompt(discarded: number): string {
  const count = Number.isFinite(discarded) ? Math.max(0, Math.floor(discarded)) : 0;
  if (count === 0) {
    return 'A new answer replaces the current one. No later messages will be removed. You can undo right after.';
  }
  if (count === 1) {
    return 'This removes 1 later message, including every later question and answer. You can undo right after.';
  }
  return `This removes ${count} later messages, including every later question and answer. You can undo right after.`;
}

/** Wording for the edit confirmation, counting later conversation turns. */
export function editPrompt(discardedTurns: number): string {
  const count = Number.isFinite(discardedTurns) ? Math.max(0, Math.floor(discardedTurns)) : 0;
  if (count === 0) {
    return 'A new answer will be generated from the edited message. You can undo right after.';
  }
  if (count === 1) {
    return 'Editing this message removes 1 later turn, including every later question and answer. You can undo right after.';
  }
  return `Editing this message removes ${count} later turns, including every later question and answer. You can undo right after.`;
}

/** Wording for the edit undo bar, counting later conversation turns. */
export function editUndoNotice(discardedTurns: number): string {
  const count = Number.isFinite(discardedTurns) ? Math.max(0, Math.floor(discardedTurns)) : 0;
  if (count === 0) return 'Message edited. The previous answer can be restored.';
  if (count === 1) return 'Message edited. 1 later turn was removed.';
  return `Message edited. ${count} later turns were removed.`;
}
const SECRET_PATTERNS: RegExp[] = [
  /sk-[a-zA-Z0-9]{15,}/gi,
  /sk-ant-[a-zA-Z0-9]{20,}/gi,
  /xai-[a-zA-Z0-9]{20,}/gi,
  /gsk_[a-zA-Z0-9]{20,}/gi,
  /AIza[a-zA-Z0-9_-]{35}/gi,
  /ghp_[a-zA-Z0-9]{36}/gi,
  /gho_[a-zA-Z0-9]{36}/gi,
  /xox[bpsa]-[A-Za-z0-9-]+/gi,
  /(?:AKIA|ASIA)[A-Z0-9]{16}/gi,
  /(?:password|secret|token|key|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{10,}['\"]?/gi,
  /-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----/gi,
  /(?:api[_-]?key|apikey)\s*[:=]\s*['\"]([^'\"]+)['\"]/gi,
  /(?:postgres|mysql|mongodb|redis):\/\/[^\s]+/gi,
];

/** Mirror backend secret redaction before estimating the outbound context. */
export function sanitizeChatContextContent(content: string): string {
  return SECRET_PATTERNS.reduce((sanitized, pattern) => sanitized.replace(pattern, '[REDACTED]'), content);
}

export function buildChatContext(
  chat: TemporaryChat | null | undefined,
  options?: {
    maxMessages?: number;
    maxChars?: number;
    strictAlternation?: boolean;
    contextWindow?: number | null;
    maxTokens?: number | null;
    includeIncompleteMarkers?: boolean;
  },
): Array<{ role: ChatRole; content: string }> {
  if (!chat) return [];
  const budget = contextBudget(options?.contextWindow, options?.maxTokens);
  const maxMessages = options?.maxMessages ?? budget.maxMessages;
  const maxChars = options?.maxChars ?? budget.maxChars;
  const strictAlternation = options?.strictAlternation ?? false;

  // Every finished turn participates, including stopped, truncated, aborted and
  // failed ones: they carry real content, and dropping them silently orphaned
  // the user's prompt. The outbound marker records that the turn ended early.
  const eligible = chat.messages
    .filter(
      (m) =>
        isContextEligible(m.status) &&
        typeof m.content === 'string' &&
        m.content.trim().length > 0,
    )
    .map((m) => ({
      role: m.role,
      content: applyIncompleteMarker(
        sanitizeChatContextContent(m.content.trim()),
        options?.includeIncompleteMarkers === false ? 'complete' : m.status,
      ),
    }));

  // Take whole turns newest-first. The first turn that does not fit stops the
  // walk, so the selected history is always a contiguous suffix of the chat.
  let selected: Array<{ role: ChatRole; content: string }> = [];
  let totalChars = 0;
  for (let i = eligible.length - 1; i >= 0; i -= 1) {
    if (selected.length >= maxMessages) break;
    const message = eligible[i];
    if (selected.length > 0 && totalChars + message.content.length > maxChars) break;
    const content =
      message.content.length > maxChars
        ? clipMessageContent(message.content, maxChars)
        : message.content;
    selected.push({ role: message.role, content });
    totalChars += content.length;
    if (totalChars >= maxChars) break;
  }
  selected.reverse();

  while (selected.length > 0 && selected[0].role !== 'user') {
    selected.shift();
  }
  while (selected.length > 0 && selected[selected.length - 1].role !== 'user') {
    selected.pop();
  }

  // The kLLM relay accepts repeated same-role turns; the hosted Ollama path opts
  // into strict alternation because some model chat templates are rendered from
  // an alternating turn list. Merging (not dropping) keeps every user message.
  if (strictAlternation) {
    selected = enforceAlternation(selected, maxChars);
  }

  return selected;
}

/** Collapse consecutive same-role turns so a hosted prompt alternates strictly. */
export function enforceAlternation(
  messages: Array<{ role: ChatRole; content: string }>,
  maxChars = CHAT_MAX_CONTEXT_CHARS,
): Array<{ role: ChatRole; content: string }> {
  const merged: Array<{ role: ChatRole; content: string }> = [];
  for (const message of messages) {
    const previous = merged[merged.length - 1];
    if (previous && previous.role === message.role) {
      merged[merged.length - 1] = {
        role: message.role,
        content: `${previous.content}\n\n${message.content}`,
      };
    } else {
      merged.push({ ...message });
    }
  }

  let total = merged.reduce((sum, m) => sum + m.content.length, 0);
  while (merged.length > 1 && total > maxChars) {
    total -= (merged.shift() as { content: string }).content.length;
  }
  while (merged.length > 0 && merged[0].role !== 'user') merged.shift();
  while (merged.length > 0 && merged[merged.length - 1].role !== 'user') merged.pop();
  if (merged.length > 0 && total > maxChars) {
    merged[merged.length - 1] = {
      ...merged[merged.length - 1],
      content: clipMessageContent(merged[merged.length - 1].content, maxChars),
    };
  }
  return merged;
}

/** Smallest prompt allowance the backend keeps next to an output budget. */
export const MIN_CONTEXT_INPUT_TOKENS = 512;

/** Headroom kept free for provider overhead, matching the backend. */
export function contextSafetyHeadroom(contextWindow?: number | null): number {
  if (!contextWindow || !Number.isFinite(contextWindow) || contextWindow <= 0) {
    return CONTEXT_OUTPUT_RESERVE_TOKENS;
  }
  if (contextWindow < CONTEXT_OUTPUT_RESERVE_TOKENS * 4) {
    return Math.min(
      CONTEXT_OUTPUT_RESERVE_TOKENS,
      Math.max(0, Math.floor(contextWindow / 4)),
    );
  }
  return CONTEXT_OUTPUT_RESERVE_TOKENS;
}

/** Largest generation budget that still leaves a usable prompt allowance. */
export function maxOutputTokensForWindow(contextWindow?: number | null): number {
  if (!contextWindow || !Number.isFinite(contextWindow) || contextWindow <= 0) {
    return MAX_CONTEXT_OUTPUT_TOKENS;
  }
  const room =
    Math.floor(contextWindow) - contextSafetyHeadroom(contextWindow) - MIN_CONTEXT_INPUT_TOKENS;
  return Math.max(1, Math.min(room, MAX_CONTEXT_OUTPUT_TOKENS));
}

/** Output budget reserved before fitting the prompt, matching the backend. */
export function contextOutputReserve(
  contextWindow?: number | null,
  maxTokens?: number | null,
): number {
  if (typeof maxTokens === 'number' && Number.isFinite(maxTokens)) {
    // The backend clamps an override to the window before fitting; mirroring it
    // keeps the preview from promising room the request will not have.
    return Math.max(
      1,
      Math.min(Math.floor(maxTokens), maxOutputTokensForWindow(contextWindow)),
    );
  }
  if (!contextWindow || !Number.isFinite(contextWindow) || contextWindow <= 0) {
    return DEFAULT_CONTEXT_OUTPUT_TOKENS;
  }
  return Math.min(
    MAX_CONTEXT_OUTPUT_TOKENS,
    Math.max(MIN_CONTEXT_OUTPUT_TOKENS, Math.floor(contextWindow / 4)),
  );
}

export interface ContextBudget {
  maxMessages: number;
  maxChars: number;
  /** False when the model window is unknown and the fixed legacy caps apply. */
  windowed: boolean;
  /** Generation budget reserved for this request. */
  outputTokens: number;
  /** Headroom kept free for provider overhead. */
  headroom: number;
  /** True for the unknown-window fallback, so the UI can say so. */
  fallback: boolean;
}

/**
 * Budget for one request, derived from the selected model's real window so a
 * large-window model receives the whole conversation instead of 20 turns. The
 * backend is authoritative; this mirrors its arithmetic so the meter, the
 * preview and the request agree.
 */
export function contextBudget(
  contextWindow?: number | null,
  maxTokens?: number | null,
): ContextBudget {
  if (!contextWindow || !Number.isFinite(contextWindow) || contextWindow <= 0) {
    return {
      maxMessages: CHAT_MAX_CONTEXT_MESSAGES,
      maxChars: CHAT_MAX_CONTEXT_CHARS,
      windowed: false,
      outputTokens: DEFAULT_CONTEXT_OUTPUT_TOKENS,
      headroom: CONTEXT_OUTPUT_RESERVE_TOKENS,
      fallback: true,
    };
  }
  const reserve = contextOutputReserve(contextWindow, maxTokens);
  const headroom = contextSafetyHeadroom(contextWindow);
  const inputTokens = Math.max(0, Math.floor(contextWindow) - reserve - headroom);
  return {
    maxMessages: CHAT_CONTEXT_MESSAGES_GLOBAL,
    maxChars: Math.max(1, Math.min(CHAT_CONTEXT_CHARS_GLOBAL, inputTokens * CHARS_PER_TOKEN_FIT)),
    windowed: true,
    outputTokens: reserve,
    headroom,
    fallback: false,
  };
}

/** Character budget for a chat context derived from the selected model window. */
export function contextCharBudget(
  contextWindow?: number | null,
  maxTokens?: number | null,
): number {
  return contextBudget(contextWindow, maxTokens).maxChars;
}

export interface KllmModelLike {
  key: string;
  model?: string;
  status?: string;
  loaded?: boolean;
  ready?: boolean;
  readiness?: string;
  reason_code?: string;
  context_window?: number | null;
  vision?: boolean;
  provider?: string;
  category?: string;
  display_name?: string;
  resident?: boolean;
  installed?: boolean;
  admin_loadable?: boolean;
  digest?: string | null;
  last_verified_at?: string | null;
  runtime_unknown?: boolean;
  partial?: boolean;
  load_state?: string | null;
  runtime_state?: string;
  runtime_reason?: string | null;
}

export const HOSTED_PROVIDER = 'hosted-ollama';
export const KLLM_PROVIDER = 'kllm';
export const CLOUD_PROVIDER = 'kllm-cloud';
export const HOSTED_CATEGORY_LABEL = 'Hosted models managed by Revora';
export const CLOUD_CATEGORY_LABEL = 'Cloud models managed by Revora';
export const HOSTED_PROVIDER_LABEL = 'Hosted Models';
export const KLLM_PROVIDER_LABEL = 'kLLM';
export const CLOUD_PROVIDER_LABEL = 'kLLM Cloud';

export function isHostedModel(model: KllmModelLike | null | undefined): boolean {
  return !!model && (model.provider === HOSTED_PROVIDER || model.category === 'hosted');
}

/**
 * kLLM Cloud rows carry their own provider and category. A stored key keeps the
 * namespace even when the catalog row is gone, so the key is accepted too.
 */
export function isCloudModel(model: KllmModelLike | null | undefined): boolean {
  if (!model) return false;
  if (model.provider === CLOUD_PROVIDER || model.category === CLOUD_PROVIDER) {
    return true;
  }
  const key = (model.key ?? '').trim().toLowerCase();
  return CLOUD_ROUTING_PREFIXES.some((prefix) => key.startsWith(prefix));
}

/** Provider section heading for a model, derived from backend identity only. */
export function providerLabel(model: KllmModelLike | null | undefined): string {
  if (isCloudModel(model)) return CLOUD_PROVIDER_LABEL;
  return isHostedModel(model) ? HOSTED_PROVIDER_LABEL : KLLM_PROVIDER_LABEL;
}

/** Canonical provider identity for routing assertions. */
export function providerOf(
  model: KllmModelLike | null | undefined,
): ChatProviderId {
  if (isCloudModel(model)) return CLOUD_PROVIDER;
  return isHostedModel(model) ? HOSTED_PROVIDER : KLLM_PROVIDER;
}

/** Hosted routing prefixes accepted from stored keys, including legacy spellings. */
const HOSTED_ROUTING_PREFIXES = ['hosted-ollama:', 'hosted_ollama:'] as const;
/** Cloud routing prefix. The provider also travels separately in the request. */
const CLOUD_ROUTING_PREFIXES = ['kllm-cloud:', 'kllm_cloud:'] as const;

/** Provider derived from an opaque model key, so routing survives a missing catalog row. */
export function providerForKey(key: string | null | undefined): ChatProviderId {
  if (typeof key !== 'string') return KLLM_PROVIDER;
  const lower = key.trim().toLowerCase();
  if (CLOUD_ROUTING_PREFIXES.some((prefix) => lower.startsWith(prefix))) {
    return CLOUD_PROVIDER;
  }
  return HOSTED_ROUTING_PREFIXES.some((prefix) => lower.startsWith(prefix))
    ? HOSTED_PROVIDER
    : KLLM_PROVIDER;
}

/** Minimal identity needed to label or icon a model without importing React. */
export interface ModelIdentity {
  key?: string | null;
  display_name?: string | null;
  provider?: string | null;
  category?: string | null;
}

/**
 * Revora prefixes a hosted model's routing key with its provider. Strip only
 * those known internal prefixes; never guess about arbitrary model names.
 */
const MODEL_ROUTING_PREFIXES = [
  ...HOSTED_ROUTING_PREFIXES,
  ...CLOUD_ROUTING_PREFIXES,
  'kllm:',
] as const;

export function stripModelRoutingPrefix(value: string | null | undefined): string {
  const trimmed = (value ?? '').trim();
  if (!trimmed) return '';
  const lower = trimmed.toLowerCase();
  for (const prefix of MODEL_ROUTING_PREFIXES) {
    if (lower.startsWith(prefix)) return trimmed.slice(prefix.length);
  }
  return trimmed;
}

/**
 * Canonical key sent to the backend. A hosted key always uses the one prefix the
 * API accepts (`hosted-ollama:`); a kLLM key is sent bare because the provider
 * travels separately in the request. The original requested key stays on the
 * message for attribution, so canonicalising never rewrites history.
 */
export function canonicalModelKey(value: string | null | undefined): string {
  const trimmed = (value ?? '').trim();
  if (!trimmed) return '';
  const lower = trimmed.toLowerCase();
  for (const prefix of HOSTED_ROUTING_PREFIXES) {
    if (lower.startsWith(prefix)) {
      return `${HOSTED_PROVIDER}:${trimmed.slice(prefix.length)}`;
    }
  }
  for (const prefix of CLOUD_ROUTING_PREFIXES) {
    if (lower.startsWith(prefix)) {
      return `${CLOUD_PROVIDER}:${trimmed.slice(prefix.length)}`;
    }
  }
  if (lower.startsWith('kllm:')) return trimmed.slice('kllm:'.length);
  return trimmed;
}

/** Display label for a model: prefer the backend name, else clean the key. */
export function modelDisplayName(model: ModelIdentity | null | undefined): string {
  if (!model) return '';
  return stripModelRoutingPrefix(model.display_name || model.key);
}

/**
 * Identity for a selected key that is no longer in the catalog. It keeps the
 * icon and label equivalent to a live row while staying unavailable, so the
 * composer trigger and the Chat header never disagree about what is selected.
 */
export function fallbackModelForKey(key: string): KllmModelLike {
  const provider = providerForKey(key);
  return {
    key,
    display_name: stripModelRoutingPrefix(key),
    status: 'unknown',
    ready: false,
    readiness: 'unknown',
    reason_code: 'not_in_catalog',
    provider,
    category:
      provider === CLOUD_PROVIDER
        ? CLOUD_PROVIDER
        : provider === HOSTED_PROVIDER
          ? 'hosted'
          : 'kllm',
  };
}

/**
 * Resolve a selected key against the catalog. Canonical routing keys are
 * compared so a legacy `hosted_ollama:`/`kllm:` key still finds its live row;
 * a key that is truly gone keeps an equivalent, non-selectable identity.
 */
export function resolveSelectedModel(
  models: KllmModelLike[] | null | undefined,
  key: string | null | undefined,
): KllmModelLike | null {
  if (!key) return null;
  const wanted = canonicalModelKey(key);
  const found = (models ?? []).find((model) => canonicalModelKey(model.key) === wanted);
  return found ?? fallbackModelForKey(key);
}

/**
 * Full identity for an assistant response header. The bare confirmed model id
 * from telemetry is not enough to resolve an icon: a hosted model such as
 * `smollm:135m` has no routed prefix there and would fall back to the kLLM
 * logo. Combining the stored provenance with the confirmed id keeps every
 * surface on the same icon.
 */
export function responseModelIdentity(
  message: Pick<ChatMessage, 'model' | 'provider' | 'upstreamModel'> | null | undefined,
  confirmedModel?: string | null,
): ModelIdentity | null {
  const requested = message?.model?.trim() || null;
  const confirmed = confirmedModel?.trim() || message?.upstreamModel?.trim() || null;
  if (!requested && !confirmed) return null;

  const provider = message?.provider ?? providerForKey(requested ?? confirmed);
  return {
    key: requested ?? confirmed,
    display_name: confirmed ?? undefined,
    provider,
    category:
      provider === CLOUD_PROVIDER
        ? CLOUD_PROVIDER
        : provider === HOSTED_PROVIDER
          ? 'hosted'
          : undefined,
  };
}

export type ModelFamily =
  | 'meta'
  | 'qwen'
  | 'gemma'
  | 'mistral'
  | 'deepseek'
  | 'microsoft'
  | 'huggingface';

/** Family logo to use from @lobehub/icons when the model name is unambiguous. */
export function modelFamily(model: ModelIdentity | null | undefined): ModelFamily | null {
  const text = `${model?.key ?? ''} ${model?.display_name ?? ''}`.toLowerCase();
  if (!text.trim()) return null;
  // Ollama tags append versions directly (llama3.2, qwen2.5), so a trailing
  // word boundary would miss the common case. Accept a separator, a digit or
  // end of string instead.
  if (/\bllama(?:[-_.:]|\d|$)/.test(text)) return 'meta';
  if (/\bqwen(?:[-_.:]|\d|$)/.test(text)) return 'qwen';
  if (/\bgemma(?:[-_.:]|\d|$)/.test(text)) return 'gemma';
  if (/\b(?:mistral|mixtral|codestral|ministral|pixtral|devstral|magistral)(?:[-_.:]|\d|$)/.test(text)) {
    return 'mistral';
  }
  if (/\bdeepseek(?:[-_.:]|\d|$)/.test(text)) return 'deepseek';
  if (/\bphi(?:-?\d+(?:\.\d+)?)?\b/i.test(text)) return 'microsoft';
  if (/\bsmollm\b/i.test(text)) return 'huggingface';
  return null;
}

/** Provider icon slug used when no family logo matches. */
export type ModelProviderIconSlug = string;

export function modelProviderSlug(
  model: ModelIdentity | null | undefined,
): ModelProviderIconSlug {
  if (!model) return 'kllm';
  const provider = (model.provider ?? '').trim().toLowerCase();
  const key = (model.key ?? '').trim().toLowerCase();
  if (
    model.category === CLOUD_PROVIDER ||
    provider === CLOUD_PROVIDER ||
    provider === 'kllm_cloud' ||
    CLOUD_ROUTING_PREFIXES.some((prefix) => key.startsWith(prefix))
  ) {
    return CLOUD_PROVIDER;
  }
  if (
    model.category === 'hosted' ||
    provider === HOSTED_PROVIDER ||
    provider === 'hosted_ollama' ||
    HOSTED_ROUTING_PREFIXES.some((prefix) => key.startsWith(prefix))
  ) {
    return 'ollama';
  }
  // Admin overrides carry the registered provider slug. Let the shared
  // ProviderIcon resolve its own brand (OpenAI, Gemini, Anthropic, …) instead of
  // mislabelling every unrecognised family as kLLM.
  if (provider && provider !== KLLM_PROVIDER) return provider;
  return 'kllm';
}

/** Management attribution shown beside an active model name. */
export const REVORA_MANAGEMENT_LABEL = 'Managed by Revora';
/**
 * kLLM is integrated and managed through Revora. Kept as a named constant for
 * call-site clarity; value matches {@link REVORA_MANAGEMENT_LABEL}. Never use
 * this for third-party or independently managed providers.
 */
export const KLLM_MANAGEMENT_LABEL = REVORA_MANAGEMENT_LABEL;
/** kLLM identity + management attribution, e.g. for service-level headings. */
export const KLLM_IDENTITY_LABEL = `kLLM — ${REVORA_MANAGEMENT_LABEL}`;
/** kLLM Cloud identity + management attribution. */
export const CLOUD_IDENTITY_LABEL = `kLLM Cloud — ${REVORA_MANAGEMENT_LABEL}`;
/** Supporting contextual description for kLLM surfaces. */
export const KLLM_SUPPORT_DESCRIPTION =
  'kLLM is integrated and managed through Revora. Model availability, configuration, and access are controlled through the Revora platform.';
/** Supporting contextual description for kLLM Cloud surfaces. */
export const CLOUD_SUPPORT_DESCRIPTION =
  'kLLM Cloud is an independent managed provider. Only models an administrator approves appear here, and Chat and Reviews can be enabled separately for each model.';

export function managementLabelForModel(model: ModelIdentity | null | undefined): string {
  const slug = modelProviderSlug(model);
  if (slug === 'ollama') return REVORA_MANAGEMENT_LABEL;
  if (slug === CLOUD_PROVIDER) return REVORA_MANAGEMENT_LABEL;
  if (slug === 'kllm') return KLLM_MANAGEMENT_LABEL;
  return `Managed by ${slug}`;
}

/**
 * Readable provider source for a model: "kLLM", "Hosted Models" or "kLLM Cloud".
 * Derived from provider, category or routing prefix, so the same model name from
 * different providers always gets a different label. Never returns a raw prefix.
 */
export function providerSourceLabel(model: ModelIdentity | null | undefined): string {
  const slug = modelProviderSlug(model);
  if (slug === CLOUD_PROVIDER) return CLOUD_PROVIDER_LABEL;
  if (slug === 'ollama') return HOSTED_PROVIDER_LABEL;
  if (slug === 'kllm') return KLLM_PROVIDER_LABEL;
  // Unknown provider id: show it as a readable word rather than a slug.
  return slug
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Provenance stamped on a turn when it is created: the model key, its provider
 * and the clean catalog name. The catalog name is used only when it belongs to
 * the same model, so a stale selection never names a turn after another model.
 */
export function turnProvenance(
  chatModel: string | null | undefined,
  catalogModel: KllmModelLike | null | undefined,
): MessageProvenance {
  if (!chatModel) return { model: null, provider: null, displayName: null };
  const matches =
    !!catalogModel && canonicalModelKey(catalogModel.key) === canonicalModelKey(chatModel);
  return {
    model: chatModel,
    provider: providerForKey(chatModel),
    displayName: matches ? modelDisplayName(catalogModel) || null : null,
  };
}

/** Consistent short context label, e.g. 4096 tokens -> 4K. */
export function formatContextWindow(tokens?: number | null): string | null {
  if (typeof tokens !== 'number' || !Number.isFinite(tokens) || tokens <= 0) return null;
  return `${Math.round(tokens / 1024)}K`;
}

/**
 * Output budget for one request, mirroring the backend exactly: the window's
 * safety headroom and the fitted prompt are subtracted, a caller override is
 * clamped to the window, and the result never leaves [1, 16384].
 */
export function resolveRequestOutputTokens(
  contextWindow: number | null | undefined,
  messages: ReadonlyArray<{ content: string }>,
  maxTokens?: number | null,
): number {
  const window =
    typeof contextWindow === 'number' && Number.isFinite(contextWindow) && contextWindow > 0
      ? Math.floor(contextWindow)
      : null;
  const requested =
    typeof maxTokens === 'number' && Number.isFinite(maxTokens) ? Math.floor(maxTokens) : null;
  if (!window) {
    const target = requested ?? DEFAULT_CONTEXT_OUTPUT_TOKENS;
    return Math.max(1, Math.min(target, MAX_CONTEXT_OUTPUT_TOKENS));
  }
  const inputTokens = Math.ceil(
    messages.reduce((sum, message) => sum + (message.content?.length ?? 0), 0) /
      CHARS_PER_TOKEN_FIT,
  );
  const reserve = contextOutputReserve(window, requested);
  const target = requested ?? Math.min(DEFAULT_CONTEXT_OUTPUT_TOKENS, reserve);
  const remaining = window - inputTokens - contextSafetyHeadroom(window);
  const allowed = Math.min(target, reserve, Math.max(1, remaining));
  return Math.max(1, Math.min(allowed, MAX_CONTEXT_OUTPUT_TOKENS));
}

export interface ContextMeter {
  /** Estimated prompt tokens for the NEXT request after the same fitting pass. */
  promptTokens: number;
  /** Output budget the next request will actually ask for. */
  outputTokens: number;
  /** The prompt's own usage. Never includes the reply reserve or headroom. */
  usedTokens: number;
  /** promptTokens + outputTokens + headroom: the next request's total budget. */
  nextRequestTokens: number;
  contextWindow: number | null;
  /** Percentage of the window occupied by the prompt only. */
  usedPct: number | null;
  /** Window tokens not occupied by the prompt (before reserve/headroom). */
  remaining: number | null;
  /** True when the next request's prompt + reserve + headroom fits. */
  nextRequestFits: boolean | null;
  /** Window tokens left after prompt + reply reserve + headroom. */
  spareAfterNextRequest: number | null;
  headroom: number;
  messages: number;
  /** Messages were clipped to fit the window. */
  clipped: boolean;
  /** The window is unknown, so counts are a conservative estimate. */
  fallback: boolean;
  /** Previous response's reported usage, shown as secondary context only. */
  historicalTokens: number | null;
}

/**
 * The context meter for one chat and one model.
 *
 * It is derived from the selected chat's fitted history. The bar and percentage
 * count the prompt only; the resolved output budget and safety headroom are
 * returned as separate reservations, so an empty chat is 0% even though the
 * next request reserves room for a reply. Switching tabs or models can never
 * show another chat's numbers, and historical usage is separate metadata.
 */
export function nextRequestContextMeter(
  chat: TemporaryChat | null | undefined,
  contextWindow?: number | null,
  options?: {
    maxTokens?: number | null;
    historicalTokens?: number | null;
    includeIncompleteMarkers?: boolean;
  },
): ContextMeter {
  const window =
    typeof contextWindow === 'number' && Number.isFinite(contextWindow) && contextWindow > 0
      ? Math.floor(contextWindow)
      : null;
  const requested =
    typeof options?.maxTokens === 'number' && Number.isFinite(options.maxTokens)
      ? Math.floor(options.maxTokens)
      : null;
  const clampedRequest = requested == null ? null : contextOutputReserve(window, requested);
  const provider = providerForKey(chat?.model);
  const messages = buildChatContext(chat, {
    contextWindow: window,
    maxTokens: clampedRequest,
    strictAlternation: provider === HOSTED_PROVIDER,
    includeIncompleteMarkers: options?.includeIncompleteMarkers,
  });
  const promptTokens = Math.ceil(
    messages.reduce((sum, message) => sum + message.content.length, 0) / CHARS_PER_TOKEN_FIT,
  );
  const outputTokens = resolveRequestOutputTokens(window, messages, clampedRequest);
  const headroom = contextSafetyHeadroom(window);
  // The meter's numerator is the prompt's own estimated usage. The reply
  // reserve and safety headroom are separate budget reservations, so an empty
  // chat is 0%, never 25% merely because a reply will be requested.
  const usedTokens = promptTokens;
  const nextRequestTokens = promptTokens + outputTokens + headroom;
  const historical =
    typeof options?.historicalTokens === 'number' && Number.isFinite(options.historicalTokens)
      ? Math.max(0, Math.round(options.historicalTokens))
      : null;
  return {
    promptTokens,
    outputTokens,
    usedTokens,
    nextRequestTokens,
    contextWindow: window,
    usedPct: window ? Math.min(100, Math.round((usedTokens / window) * 1000) / 10) : null,
    remaining: window ? Math.max(0, window - usedTokens) : null,
    nextRequestFits: window ? nextRequestTokens <= window : null,
    spareAfterNextRequest: window ? window - nextRequestTokens : null,
    headroom,
    messages: messages.length,
    clipped: messages.some((message) => isClippedContent(message.content)),
    fallback: window === null,
    historicalTokens: historical,
  };
}

export interface GroupedModels {
  ready: KllmModelLike[];
  loading: KllmModelLike[];
  verifying: KllmModelLike[];
  unloaded: KllmModelLike[];
  failed: KllmModelLike[];
  unavailable: KllmModelLike[];
}

export function isModelSelectable(model: KllmModelLike | null | undefined): boolean {
  // A model is selectable unless it is *confirmed* unavailable. Unverified
  // models remain selectable but are labelled honestly (not "Ready").
  return !!model && model.ready === true && model.readiness !== 'unavailable';
}

export function groupModels(models: KllmModelLike[] | null | undefined): GroupedModels {
  const groups: GroupedModels = {
    ready: [],
    loading: [],
    verifying: [],
    unloaded: [],
    failed: [],
    unavailable: [],
  };
  for (const model of models ?? []) {
    if (isModelSelectable(model)) {
      groups.ready.push(model);
    } else if (model.readiness === 'verifying' || model.status === 'verifying') {
      groups.verifying.push(model);
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

/**
 * Resolve a chat's model selection. An existing selection is never replaced:
 * catalog refreshes must not silently switch model or provider. A default is
 * chosen only when the chat has no selection yet.
 */
export function pickDefaultModel(
  models: KllmModelLike[] | null | undefined,
  selected: string | null | undefined,
): string | null {
  if (selected) return selected;
  const ready = (models ?? []).filter(isModelSelectable);
  if (ready.length === 0) return null;
  return ready[0].key;
}

/** Human-readable explanation derived from the backend reason code. */
const REASON_TEXT: Record<string, string> = {
  model_not_loaded: 'Installed but not loaded. An administrator must load it.',
  model_loading: 'Loading on the runtime.',
  model_verifying: 'Load started; waiting for runtime confirmation.',
  runtime_unknown: 'Runtime state could not be verified.',
  discovery_partial: 'Discovery is incomplete.',
  model_failed: 'The runtime reported a failure.',
  model_not_found: 'This model is not available on the runtime.',
  no_ready_backend: 'No healthy backend is serving this model.',
  kllm_unreachable: 'kLLM is unreachable.',
  kllm_state_stale: 'kLLM status is stale.',
  hosted_unreachable: 'Hosted Ollama is unreachable.',
  hosted_state_stale: 'Hosted model status is stale.',
  admin_disabled: 'Disabled by an administrator.',
  kllm_cloud_disabled: 'kLLM Cloud is currently unavailable.',
  kllm_cloud_unreachable: 'kLLM Cloud is unreachable.',
  kllm_cloud_catalog_stale: 'The kLLM Cloud catalogue is stale.',
  kllm_cloud_not_configured: 'kLLM Cloud is not configured on this server.',
  not_approved: 'An administrator has not approved this model yet.',
  chat_not_enabled: 'An administrator has not enabled this model for Chat.',
  review_not_enabled: 'An administrator has not enabled this model for Reviews.',
  model_disabled: 'This model is temporarily disabled by an administrator.',
  model_removed: 'This model is no longer offered by kLLM Cloud.',
};

export function readinessReason(model: KllmModelLike | null | undefined): string | null {
  if (!model) return null;
  if (isModelSelectable(model)) return null;
  const code = model.reason_code ?? '';
  if (REASON_TEXT[code]) return REASON_TEXT[code];
  if (model.load_state) return `Load operation: ${model.load_state}.`;
  return null;
}

export interface CatalogGroups {
  kllm: GroupedModels;
  cloud: GroupedModels;
  hosted: GroupedModels;
}

/** Partition the unified catalog by provider, then group each by readiness. */
export function groupCatalogModels(
  models: KllmModelLike[] | null | undefined,
): CatalogGroups {
  const kllm: KllmModelLike[] = [];
  const cloud: KllmModelLike[] = [];
  const hosted: KllmModelLike[] = [];
  for (const model of models ?? []) {
    if (isCloudModel(model)) cloud.push(model);
    else if (isHostedModel(model)) hosted.push(model);
    else kllm.push(model);
  }
  return {
    kllm: groupModels(kllm),
    cloud: groupModels(cloud),
    hosted: groupModels(hosted),
  };
}

/** Structural catalog shape; keeps this pure state module free of API imports. */
export interface ChatCatalogLike {
  models?: KllmModelLike[] | null;
  providers?: ReadonlyArray<{
    provider?: string | null;
    enabled?: boolean;
    configured?: boolean;
    reachable?: boolean;
  }> | null;
}

/** A managed provider is usable only when it is enabled, configured and reachable. */
export function isManagedProviderReachable(
  catalog: ChatCatalogLike | null | undefined,
  providerId: string,
): boolean {
  const provider = catalog?.providers?.find((item) => item.provider === providerId);
  return !!provider && provider.enabled === true && provider.configured === true && provider.reachable === true;
}

/**
 * Models shown in Chat. Offline/unconfigured kLLM and kLLM Cloud models are
 * hidden entirely; hosted and third-party BYOK models stay visible.
 */
export function visibleChatModels(catalog: ChatCatalogLike | null | undefined): KllmModelLike[] {
  const models = catalog?.models ?? [];
  const kllmOk = isManagedProviderReachable(catalog, KLLM_PROVIDER);
  const cloudOk = isManagedProviderReachable(catalog, CLOUD_PROVIDER);
  return models.filter((model) => {
    if (isCloudModel(model)) return cloudOk;
    if (isHostedModel(model)) return true;
    // Independently configured BYOK providers are not managed by kLLM.
    const provider = (model.provider ?? '').trim().toLowerCase();
    if (provider && provider !== KLLM_PROVIDER && provider !== 'ollama') return true;
    return kllmOk;
  });
}
