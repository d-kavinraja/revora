'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDownIcon, Trash2Icon } from 'lucide-react';

import { api } from '@/lib/api';
import {
  ChatAuthError,
  ChatRequestError,
  type ChatModelEvent,
  type ChatProgressEvent,
  type ChatTimingsEvent,
  type ChatUsageEvent,
  type ReasoningEffort,
  streamChatCompletion,
} from '@/lib/chat-api';
import {
  CHAT_MAX_CHATS,
  CHAT_MAX_MESSAGE_CHARS,
  CHAT_MAX_MESSAGES_PER_CHAT,
  HOSTED_PROVIDER,
  INCOMPLETE_FINISH_REASON,
  buildChatContext,
  canonicalModelKey,
  coalesceMetricsPatch,
  computeContextUsed,
  computeTokensPerSecond,
  editPrompt,
  editUndoNotice,
  finalStatusFor,
  isModelSelectable,
  nextRequestContextMeter,
  pickDefaultModel,
  planMessageEdit,
  providerForKey,
  regenerationPrompt,
  resolveSelectedModel,
  undoNotice,
  withPendingChatDraft,
  type ChatMessage,
  type EditPlan,
  type RegenerationPlan,
  type ResponseMetrics,
  type ResponsePhase,
  type TemporaryChat,
} from '@/lib/chat-state';
import { createStreamRegistry, type StreamRegistry } from '@/lib/stream-lifecycle';
import { formatSpeechError, insertTranscript } from '@/lib/speech';
import { useChatModes } from '@/lib/use-chat-modes';
import { useAuthStore } from '@/store/useAuthStore';
import { useChatStore } from '@/store/useChatStore';

import Image from 'next/image';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { ManagedByRevora } from '@/components/shared/managed-by-revora';
import { ChatComposer } from './chat-composer';
import { useSpeechToText } from './use-speech-to-text';
import { ChatTabs } from './chat-tabs';
import { ChatMessageList } from './chat-message-list';
import { ChatProviderStatusBanners } from './chat-provider-status-banners';
import { ChatTopBar } from './chat-top-bar';

const SCROLL_NEAR_BOTTOM_PX = 80;

// A failed request can mean the provider's readiness changed. Only these codes
// trigger a catalog refresh; content/prompt problems do not.
const READINESS_ERROR_CODES = new Set([
  'model_not_loaded',
  'model_not_found',
  'runtime_unknown',
  'no_ready_backend',
  'model_failed',
  'hosted_unreachable',
  'hosted_state_stale',
  'kllm_unreachable',
  'kllm_state_stale',
  'hosted_busy',
  'kllm_busy',
]);

type ChatMenu = 'context' | 'model' | 'effort' | null;

interface ChatShellProps {
  onKllmStatusChange?: (unavailable: boolean) => void;
  activeMode?: 'temporary' | 'persistent';
  isActive?: boolean;
  temporaryEnabled?: boolean;
  persistentEnabled?: boolean;
  onModeChange?: (mode: 'temporary' | 'persistent') => void;
}

export function ChatShell({
  onKllmStatusChange,
  activeMode = 'temporary',
  isActive = true,
  temporaryEnabled = true,
  persistentEnabled = false,
  onModeChange,
}: ChatShellProps = {}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: chatModes } = useChatModes();
  const chatFlagEnabled = chatModes?.temporary_enabled === true;

  const activeId = useChatStore((s) => s.activeId);
  const chatsRecord = useChatStore((s) => s.chats);
  const order = useChatStore((s) => s.order);
  const ensureActiveChat = useChatStore((s) => s.ensureActiveChat);
  const createNewChat = useChatStore((s) => s.createNewChat);
  const selectChat = useChatStore((s) => s.selectChat);
  const deleteChat = useChatStore((s) => s.deleteChat);
  const clearChat = useChatStore((s) => s.clearChat);
  const setChatModel = useChatStore((s) => s.setChatModel);
  const beginTurn = useChatStore((s) => s.beginTurn);
  const appendAssistantDelta = useChatStore((s) => s.appendAssistantDelta);
  const finishAssistantMessage = useChatStore((s) => s.finishAssistantMessage);
  const setConfirmedModel = useChatStore((s) => s.setConfirmedModel);
  const planRegeneration = useChatStore((s) => s.planRegeneration);
  const applyRegeneration = useChatStore((s) => s.applyRegeneration);
  const applyMessageEdit = useChatStore((s) => s.applyMessageEdit);
  const restoreMessages = useChatStore((s) => s.restoreMessages);
  const setDraftValue = useChatStore((s) => s.setDraft);
  const clearDraft = useChatStore((s) => s.clearDraft);
  const markStreaming = useChatStore((s) => s.markStreaming);
  const clearStreaming = useChatStore((s) => s.clearStreaming);
  const resetAll = useChatStore((s) => s.resetAll);

  // Set only when the store refuses a send (the chat cannot fit the user turn
  // plus its answer), so the composer can explain the refusal instead of
  // silently dropping the message.
  const [sendError, setSendError] = useState<string | null>(null);
  const [speechInsertToken, setSpeechInsertToken] = useState(0);
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>('medium');
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [openMenu, setOpenMenu] = useState<ChatMenu>(null);
  const [metrics, setMetrics] = useState<Record<string, ResponseMetrics>>({});
  // A ref mirrors metrics so the edit snapshot can read the exact telemetry of
  // the answer being replaced before it is dropped from state.
  const metricsRef = useRef<Record<string, ResponseMetrics>>({});
  // Regenerating a turn that is not the last one deletes later messages, so the
  // exact count is confirmed first and the removed turns stay undoable.
  const [pendingRegeneration, setPendingRegeneration] = useState<{
    chatId: string;
    plan: RegenerationPlan;
  } | null>(null);
  const [undoRegeneration, setUndoRegeneration] = useState<{
    chatId: string;
    messages: ChatMessage[];
    discarded: number;
    // Id of the generation this snapshot replaced: undo only applies while that
    // generation is still the tail, so it can never discard newer turns.
    appliedTailId: string;
  } | null>(null);
  // Editing a sent user turn replaces it in place and drops every later turn.
  // The shell owns the editing id so a chat switch can never leave a stale editor.
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [pendingEdit, setPendingEdit] = useState<{
    chatId: string;
    plan: EditPlan;
  } | null>(null);
  const [undoEdit, setUndoEdit] = useState<{
    chatId: string;
    messages: ChatMessage[];
    discarded: number;
    appliedTailId: string;
    // Telemetry of the answer(s) replaced by the edit, restored with the
    // messages so undo brings back content, attribution and metrics together.
    metrics: Record<string, ResponseMetrics>;
  } | null>(null);
  // Random chat ids are generated in the in-memory store at module init, so they
  // differ between SSR and hydration. Derive DOM ids from a stable useId base instead.
  const panelIdBase = useId();
  // One generation owns the store at a time. Every stream callback checks its
  // own token, so a stopped, superseded or unmounted stream can never mutate
  // newer history, no matter how late its callbacks arrive.
  // Lazy state is the React-sanctioned way to create a mutable instance once:
  // these objects must survive re-renders but never participate in them.
  const [streamRegistry] = useState<StreamRegistry>(createStreamRegistry);
  const listRef = useRef<HTMLDivElement | null>(null);
  const thinkingOrbRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const flushFrameRef = useRef<number | null>(null);
  // Telemetry for every live generation, keyed by message id: two chats can
  // stream at once, so one pending patch slot would drop the other's numbers.
  const pendingMetricsRef = useRef<Map<string, Partial<ResponseMetrics>>>(new Map());

  const contextOpen = openMenu === 'context';

  useEffect(() => {
    metricsRef.current = metrics;
  }, [metrics]);

  const chats = useMemo(() => order.map((id) => chatsRecord[id]).filter(Boolean), [order, chatsRecord]);
  const activeChat = activeId ? chatsRecord[activeId] ?? null : null;
  const [speechTranscript, setSpeechTranscript] = useState<string | null>(null);
  const [prevActiveId, setPrevActiveId] = useState<string | null>(activeId);
  if (activeId !== prevActiveId) {
    setPrevActiveId(activeId);
    setSpeechTranscript(null);
  }
  const activeIndex = chats.findIndex((c) => c?.id === activeId);
  const isFreshChat = !activeChat || activeChat.messages.length === 0;
  // Composer text is per chat, so switching tabs never carries a draft into
  // another conversation. It lives only in this in-memory store.
  const draft = useChatStore((s) => (activeId ? s.drafts[activeId] ?? '' : ''));
  const streaming = useChatStore((s) => s.streaming);

  const speechStatusQuery = useQuery({
    queryKey: ['speech', 'status'],
    queryFn: ({ signal }) => api.getSpeechStatus(signal),
    staleTime: 0,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      if (state && state !== 'ready') return 5_000;
      return 15_000;
    },
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: 0,
    enabled: chatFlagEnabled && isActive,
  });
  // Fail closed: a failed status read must hide the control, not keep a stale
  // "enabled" value from the last successful poll. The backend still enforces
  // the admin toggle on every transcription request.
  const speechEnabled =
    isActive &&
    chatFlagEnabled &&
    !speechStatusQuery.isError &&
    speechStatusQuery.data?.enabled === true;
  const speechReadiness = speechStatusQuery.data?.state ?? 'unavailable';

  const statusQuery = useQuery({
    queryKey: ['chat', 'models'],
    queryFn: ({ signal }) => api.getChatModels(signal),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: 1,
    enabled: chatFlagEnabled && isActive,
  });

  // Notify parent when the model catalog becomes unavailable/stale so the
  // SideRays background animation can be disabled.
  useEffect(() => {
    if (!onKllmStatusChange) return;
    const unavailable =
      !!statusQuery.data &&
      (!statusQuery.data.enabled ||
        !statusQuery.data.reachable ||
        !!statusQuery.data.stale);
    onKllmStatusChange(unavailable);
  }, [statusQuery.data, onKllmStatusChange]);

  // The in-memory store starts empty so SSR and hydration render the same tree.
  // The first chat is created only after mount, and recreated if a logout or
  // account change resets the store while this shell is still mounted.
  useEffect(() => {
    if (!activeId) ensureActiveChat();
  }, [activeId, ensureActiveChat]);

  useEffect(() => {
    if (!activeChat) return;
    const next = pickDefaultModel(statusQuery.data?.models, activeChat.model);
    if (next !== activeChat.model) setChatModel(activeChat.id, next);
  }, [activeChat, setChatModel, statusQuery.data?.models]);

  useEffect(() => {
    const el = listRef.current;
    if (!el || isFreshChat) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      const near = distance < SCROLL_NEAR_BOTTOM_PX;
      stickToBottomRef.current = near;
      setShowScrollButton(!near);
    };
    onScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [activeId, isFreshChat]);

  // Context popover interactions are owned by ChatContextUsage.

  useEffect(() => {
    const el = listRef.current;
    if (!el || !stickToBottomRef.current || isFreshChat) return;
    el.scrollTop = el.scrollHeight;
  }, [activeChat?.messages, streaming, activeId, isFreshChat]);

  // One flush per animation frame carries BOTH the accumulated text and the
  // latest telemetry. Previously timings_per_token produced a setState per token
  // (plus one for the chunk model), starving the main thread so the answer was
  // only painted after generation ended.
  const flushPending = useCallback(() => {
    // Each live generation owns its own buffer, so one frame can safely apply
    // text for several chats without mixing their answers.
    for (const token of streamRegistry.tokens()) {
      const delta = token.buffer.flush();
      if (delta) appendAssistantDelta(token.chatId, token.messageId, delta);
    }
    if (pendingMetricsRef.current.size === 0) return;
    const entries = [...pendingMetricsRef.current.entries()];
    pendingMetricsRef.current.clear();
    setMetrics((prev) => {
      const next = { ...prev };
      for (const [messageId, patch] of entries) {
        next[messageId] = {
          ...(next[messageId] ?? {
            phase: 'preparing' as ResponsePhase,
            startedAt: performance.now(),
          }),
          ...patch,
        };
      }
      return next;
    });
  }, [appendAssistantDelta, streamRegistry]);

  const cancelFrame = useCallback(() => {
    if (flushFrameRef.current === null) return;
    if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(flushFrameRef.current);
    flushFrameRef.current = null;
  }, []);

  const flushNow = useCallback(() => {
    cancelFrame();
    flushPending();
  }, [cancelFrame, flushPending]);

  const scheduleFrame = useCallback(() => {
    if (flushFrameRef.current !== null) return;
    if (typeof requestAnimationFrame !== 'function') {
      flushPending();
      return;
    }
    flushFrameRef.current = requestAnimationFrame(() => {
      flushFrameRef.current = null;
      flushPending();
    });
  }, [flushPending]);

  // Coalesce telemetry patches per message so each frame applies at most one
  // state update regardless of how many timings/model events arrived.
  const queueMetrics = useCallback((messageId: string, patch: Partial<ResponseMetrics>) => {
    const previous = pendingMetricsRef.current.get(messageId);
    const merged = coalesceMetricsPatch(
      previous ? { messageId, patch: previous } : null,
      messageId,
      patch,
    );
    pendingMetricsRef.current.set(messageId, merged.patch);
    scheduleFrame();
  }, [scheduleFrame]);

  // Unmount is a real terminal state for the in-flight turn. Persist whatever
  // text already arrived, abort the request, then finalize the captured message
  // so it can never stay `streaming` forever or be finalized by a late event of
  // a different chat. A no-op when nothing is streaming.
  useEffect(() => {
    return () => {
      // Every live generation is terminal on unmount: flush what arrived, abort
      // the request, then finalize its own message so no bubble stays
      // `streaming` forever. Other chats cannot be finalized by these tokens.
      const tokens = streamRegistry.tokens();
      flushPending();
      cancelFrame();
      streamRegistry.abortAll();
      for (const token of tokens) {
        finishAssistantMessage(token.chatId, token.messageId, 'aborted');
        // The marker lives in the store, which outlives this component: leaving
        // it behind would disable the composer for that chat on the next visit.
        clearStreaming(token.chatId, token.messageId);
      }
    };
  }, [cancelFrame, clearStreaming, finishAssistantMessage, flushPending, streamRegistry]);

  // Generation state belongs to the selected chat only: another chat streaming
  // in the background must not disable this composer or show its orb.
  const activeStreamMessageId = activeChat ? streaming[activeChat.id] : undefined;
  const isGenerating = Boolean(activeChat && activeStreamMessageId);
  const thinkingMessage = activeChat && activeStreamMessageId
    ? activeChat.messages.find((m) => m.id === activeStreamMessageId)
    : undefined;
  const isThinking = isGenerating && !thinkingMessage?.content?.trim();

  useEffect(() => {
    if (isFreshChat && listRef.current) {
      listRef.current.scrollTop = 0;
      setShowScrollButton(false);
    }
  }, [isFreshChat]);

  useEffect(() => {
    if (!isThinking || !thinkingOrbRef.current || !listRef.current) return;
    const element = listRef.current;
    const orb = thinkingOrbRef.current;
    const targetScroll = orb.offsetTop - element.clientHeight / 2 + orb.clientHeight / 2;
    element.scrollTo({ top: Math.max(0, targetScroll), behavior: 'smooth' });
  }, [isThinking]);

  const selectedModel = useMemo(
    () => resolveSelectedModel(statusQuery.data?.models, activeChat?.model),
    [activeChat?.model, statusQuery.data?.models],
  );

  const activeMetrics = activeStreamMessageId
    ? metrics[activeStreamMessageId]
    : activeChat?.messages.length
      ? metrics[activeChat.messages[activeChat.messages.length - 1]?.id ?? '']
      : undefined;
  const beamGenerationPhase: 'preparing' | 'thinking' | 'generating' | null = !activeStreamMessageId
    ? null
    : activeMetrics?.phase === 'generating'
      ? 'generating'
      : activeMetrics?.phase === 'thinking'
        ? 'thinking'
        : 'preparing';

  // The meter describes the NEXT request of the SELECTED chat with the SELECTED
  // model. Its bar/numerator is the fitted PROMPT only; the reply reserve and
  // safety headroom are separate budget rows, never consumed context. It never
  // borrows another chat's live timings, and previous response usage is shown
  // only as secondary history.
  const lastAssistantId = useMemo(() => {
    if (!activeChat) return null;
    for (let i = activeChat.messages.length - 1; i >= 0; i -= 1) {
      if (activeChat.messages[i].role === 'assistant') return activeChat.messages[i].id;
    }
    return null;
  }, [activeChat]);
  // The unsent draft is the next prompt, so it participates in the estimate.
  // It is never written into the store or into a persistent conversation.
  const contextChat = useMemo(() => withPendingChatDraft(activeChat, draft), [activeChat, draft]);
  const contextInfo = useMemo(
    () =>
      nextRequestContextMeter(contextChat, selectedModel?.context_window ?? null, {
        // Only a finished answer is "last response"; the streaming answer's
        // live usage belongs to this request, not to the secondary figure.
        historicalTokens:
          lastAssistantId && lastAssistantId !== activeStreamMessageId
            ? metrics[lastAssistantId]?.contextUsed ?? null
            : null,
      }),
    [contextChat, activeStreamMessageId, selectedModel, lastAssistantId, metrics],
  );

  const selectedModelReady = isModelSelectable(selectedModel);
  const providers = statusQuery.data?.providers ?? [];
  const enabledProviders = providers.filter((p) => p.enabled);
  const freshProviders = providers.filter(
    (p) => p.enabled && p.reachable && !p.stale && p.discovery_ok !== false,
  );
  const selectedProviderId = providerForKey(activeChat?.model);
  const selectedProviderNotice =
    providers.find((p) => p.provider === selectedProviderId)?.state === 'ready'
      ? null
      : providers.find((p) => p.provider === selectedProviderId)?.reason ?? null;
  const canCreate = order.length < CHAT_MAX_CHATS;
  const atMessageLimit = (activeChat?.messages.length ?? 0) >= CHAT_MAX_MESSAGES_PER_CHAT;

  const disabledReason = (() => {
    if (!chatFlagEnabled) return null;
    if (isGenerating) return 'A response is already being generated. Stop it before sending another message.';
    if (!activeChat) return 'Create a chat to begin.';
    if (!statusQuery.data) return statusQuery.isLoading ? 'Loading model status...' : null;
    if (enabledProviders.length === 0) return 'No AI models are available. Ask an administrator to enable a provider.';
    if (freshProviders.length === 0) return 'Model status is unavailable or stale. Refresh and try again.';
    if (!activeChat.model) return 'Select a ready model to start chatting.';
    if (!selectedModelReady) {
      return selectedProviderNotice
        ? `The selected model is not ready (${selectedProviderNotice.replace(/_/g, ' ')}). Choose another ready model.`
        : 'The selected model is not ready. Choose another ready model.';
    }
    if (atMessageLimit) return 'This temporary chat is full. Start a new chat.';
    return null;
  })();

  const handleSpeechTranscript = useCallback(
    (text: string, chatId: string): string | null => {
      const current = useChatStore.getState();
      // Insert into the chat where recording started, never whichever chat is
      // selected when a late stream event arrives. A deleted chat is ignored.
      if (!current.chats[chatId]) return formatSpeechError('speech_unavailable');
      const draftValue = current.drafts[chatId] ?? '';
      const result = insertTranscript(draftValue, text, CHAT_MAX_MESSAGE_CHARS);
      if (!result.ok) {
        return formatSpeechError(result.reason === 'empty' ? 'no_speech' : 'message_too_long');
      }
      setDraftValue(chatId, result.value);
      if (current.activeId === chatId) {
        setSpeechTranscript(result.value);
        setSpeechInsertToken((currentToken) => currentToken + 1);
      }
      setSendError(null);
      return null;
    },
    [setDraftValue],
  );

  const speech = useSpeechToText({
    enabled: speechEnabled,
    disabled: !!disabledReason || !activeChat,
    chatId: activeChat?.id ?? null,
    maxRecordingSeconds: speechStatusQuery.data?.max_recording_seconds ?? 60,
    readiness: speechReadiness,
    onTranscript: handleSpeechTranscript,
  });
  const cancelSpeech = speech.cancel;

  const handleAuthError = useCallback(async () => {
    streamRegistry.abortAll();
    resetAll();
    await useAuthStore.getState().logout({ revoke: false });
    router.replace('/login');
  }, [resetAll, router, streamRegistry]);

  // Stop ONE chat. Other chats keep streaming: that is the whole point of
  // per-chat ownership, and the aborted callbacks can only touch their own
  // message because their token is no longer current.
  const stopChat = useCallback((chatId: string) => {
    // Persist the last buffered words before the terminal status is written.
    flushNow();
    const token = streamRegistry.get(chatId);
    if (!token) return;
    finishAssistantMessage(token.chatId, token.messageId, 'stopped');
    queueMetrics(token.messageId, { phase: 'stopped', endedAt: performance.now() });
    flushNow();
    // End the token before aborting: by the time the abort surfaces, every
    // queued callback of this generation is already a no-op.
    streamRegistry.end(token);
    clearStreaming(token.chatId, token.messageId);
    token.controller.abort();
  }, [clearStreaming, finishAssistantMessage, flushNow, queueMetrics, streamRegistry]);

  const startGeneration = useCallback(async (
    chat: TemporaryChat,
    assistantMessageId: string,
  ) => {
    if (!chat.model) return;
    const providerId = providerForKey(chat.model);
    const hostedContext = providerId === HOSTED_PROVIDER;
    // The window belongs to THIS chat's model, not to whichever chat happens to
    // be selected, so a regeneration in another tab is fitted with its own.
    const modelWindow =
      statusQuery.data?.models?.find(
        (m) => canonicalModelKey(m.key) === canonicalModelKey(chat.model),
      )?.context_window ?? null;
    const context = buildChatContext(useChatStore.getState().chats[chat.id] ?? chat, {
      // The model's own window drives the budget for both providers, so a long
      // conversation is never cut to 20 turns. The hosted path is rendered as
      // strictly alternating turns; kLLM keeps same-role turns.
      contextWindow: modelWindow,
      strictAlternation: hostedContext,
      includeIncompleteMarkers: true,
    });
    if (context.length === 0) {
      finishAssistantMessage(chat.id, assistantMessageId, 'error', 'A valid user message is required.');
      return;
    }

    const controller = new AbortController();
    const token = streamRegistry.begin(chat.id, assistantMessageId, controller);
    markStreaming(chat.id, assistantMessageId);
    stickToBottomRef.current = true;
    queueMetrics(assistantMessageId, {
      phase: 'preparing',
      startedAt: performance.now(),
      contextTotal: modelWindow ?? undefined,
    });
    flushNow();

    let finalFinishReason: string | null | undefined;
    let receivedDelta = false;

    // Every callback below is a no-op unless this generation still owns the
    // stream; that is what makes a stopped or superseded stream harmless.
    const guarded = (fn: () => void) => {
      if (!streamRegistry.isCurrent(token)) return;
      fn();
    };

    const finishWithReason = (reason?: string | null) => {
      // A missing reason is not success: it is an answer that never reported
      // completion. The store records it so the bubble can say so.
      const finalReason = reason ?? INCOMPLETE_FINISH_REASON;
      const status = finalStatusFor(finalReason);
      finishAssistantMessage(chat.id, assistantMessageId, status, undefined, finalReason);
      queueMetrics(assistantMessageId, {
        phase: status === 'truncated' ? 'truncated' : status === 'complete' ? 'complete' : 'stopped',
        endedAt: performance.now(),
      });
      flushNow();
    };

    const handleTimings = (event: ChatTimingsEvent) => {
      if (event.gen_n === undefined && event.gen_ms === undefined && event.prompt_n === undefined) return;
      const patch: Partial<ResponseMetrics> = {};
      if (event.gen_n !== undefined) patch.outputTokens = event.gen_n;
      if (event.gen_ms !== undefined) patch.genMs = event.gen_ms;
      if (event.prompt_n !== undefined) patch.promptTokens = event.prompt_n;
      if (event.prompt_ms !== undefined) patch.promptMs = event.prompt_ms;
      if (event.cache_n !== undefined) patch.cachedTokens = event.cache_n;
      const tps = computeTokensPerSecond(event.gen_n, event.gen_ms);
      if (tps !== null) patch.genTps = tps;
      const used = computeContextUsed({
        prompt_n: event.prompt_n,
        cache_n: event.cache_n,
        gen_n: event.gen_n,
      });
      if (used !== null) patch.contextUsed = used;
      queueMetrics(assistantMessageId, patch);
    };

    const handleUsage = (event: ChatUsageEvent) => {
      const patch: Partial<ResponseMetrics> = {};
      if (event.completion_tokens !== undefined) patch.outputTokens = event.completion_tokens;
      if (event.prompt_tokens !== undefined) patch.promptTokens = event.prompt_tokens;
      if (event.cached_tokens !== undefined) patch.cachedTokens = event.cached_tokens;
      else if (event.cache_read_input_tokens !== undefined) patch.cachedTokens = event.cache_read_input_tokens;
      queueMetrics(assistantMessageId, patch);
    };

    try {
      let hadError = false;
      await streamChatCompletion(
        {
          model: canonicalModelKey(chat.model),
          provider: providerId,
          // Additive per-chat admission hint: lets the backend keep one chat
          // single-flight without serializing a user's other chats.
          chat_id: chat.id,
          messages: context,
          stream: true,
          reasoning_effort: reasoningEffort,
        },
        {
          onDelta: (delta) => guarded(() => {
            if (!receivedDelta) {
              receivedDelta = true;
              queueMetrics(assistantMessageId, { phase: 'generating' });
            }
            token.buffer.push(delta);
            scheduleFrame();
          }),
          onDone: (finishReason) => guarded(() => {
            finalFinishReason = finishReason;
            flushNow();
            finishWithReason(finishReason);
          }),
          onError: (err) => {
            hadError = true;
            guarded(() => {
              flushNow();
              finishAssistantMessage(chat.id, assistantMessageId, 'error', err.message);
              queueMetrics(assistantMessageId, { phase: 'error', endedAt: performance.now() });
              flushNow();
            });
            // Readiness may have changed: refresh the catalog for that provider
            // without touching the selected model or provider.
            if (err.code && READINESS_ERROR_CODES.has(err.code)) {
              void queryClient.invalidateQueries({ queryKey: ['chat', 'models'] });
            }
          },
          onUsage: (event) => guarded(() => handleUsage(event)),
          onTimings: (event) => guarded(() => handleTimings(event)),
          onStatus: () => guarded(() => {
            if (!receivedDelta) queueMetrics(assistantMessageId, { phase: 'thinking' });
          }),
          onProgress: (event: ChatProgressEvent) => guarded(() => {
            // Once real content has arrived, a late prefill progress event must
            // not revert the phase to "preparing" while text is already growing.
            if (receivedDelta) return;
            if (event.cache === undefined || event.processed === undefined || event.total === undefined) return;
            queueMetrics(assistantMessageId, {
              phase: 'preparing',
              progress: { cache: event.cache, processed: event.processed, total: event.total },
            });
          }),
          onModel: (event: ChatModelEvent) => guarded(() => {
            if (!event.name) return;
            queueMetrics(assistantMessageId, { model: event.name });
            // Only the provider's own model event records the confirmed id; the
            // requested key was already stamped when the turn was created.
            setConfirmedModel(chat.id, assistantMessageId, event.name);
          }),
        },
        controller.signal,
      );
      if (!hadError) {
        guarded(() => {
          const current = useChatStore.getState().chats[chat.id]?.messages.find((m) => m.id === assistantMessageId);
          if (current?.status !== 'streaming') return;
          flushNow();
          // The stream returned without a terminal event (no done, no [DONE]):
          // report an incomplete answer instead of a clean completion.
          finishWithReason(finalFinishReason ?? INCOMPLETE_FINISH_REASON);
        });
      }
    } catch (error) {
      if ((error as Error)?.name === 'AbortError') return;
      // A superseded stream must not report its failure over newer history.
      if (!streamRegistry.isCurrent(token)) return;
      if (error instanceof ChatAuthError) {
        await handleAuthError();
        return;
      }
      const message = error instanceof ChatRequestError ? error.message : 'Chat request failed. Please try again.';
      finishAssistantMessage(chat.id, assistantMessageId, 'error', message);
      queueMetrics(assistantMessageId, { phase: 'error', endedAt: performance.now() });
      flushNow();
      if (error instanceof ChatRequestError) {
        if (
          error.status === 503 ||
          error.status === 409 ||
          (error.code && READINESS_ERROR_CODES.has(error.code))
        ) {
          void queryClient.invalidateQueries({ queryKey: ['chat', 'models'] });
        }
      }
    } finally {
      // Flush with the captured token before releasing it, then clear the UI
      // only if this generation still owns the slot (a stop already cleared it).
      flushNow();
      if (streamRegistry.isCurrent(token)) {
        streamRegistry.end(token);
      }
      // Only this generation's marker is cleared; a newer generation of the
      // same chat keeps its own.
      clearStreaming(chat.id, assistantMessageId);
    }
  }, [
    clearStreaming,
    finishAssistantMessage,
    markStreaming,
    flushNow,
    handleAuthError,
    queryClient,
    queueMetrics,
    reasoningEffort,
    scheduleFrame,
    setConfirmedModel,
    statusQuery.data?.models,
    streamRegistry,
  ]);

  const sendMessage = useCallback(async (contentOverride?: string) => {
    const chat = activeChat;
    const content = (contentOverride ?? (speechTranscript ?? draft)).trim();
    setSpeechTranscript(null);
    // The rendered flag can lag one click behind; the registry is immediate, so
    // a double submit cannot start a second generation for the same chat.
    if (!chat || !content || isGenerating || streamRegistry.get(chat.id)) return;
    if (!chat.model || !isModelSelectable(selectedModel)) return;

    // Reserve the prompt AND its answer atomically. Appending only the prompt
    // when the last slot is free would leave an orphaned question the chat can
    // never answer, so the store refuses instead of half-writing the turn.
    const started = beginTurn(chat.id, content);
    if (!started.ok) {
      setSendError(
        started.reason === 'chat_full'
          ? `This chat has reached its ${CHAT_MAX_MESSAGES_PER_CHAT}-message limit. Start a new chat to keep going.`
          : 'That message could not be sent. Try again.',
      );
      return;
    }
    setSendError(null);
    // A manual send ends any voice capture; a late transcript must never be
    // inserted into the turn that is already leaving the composer.
    cancelSpeech();
    // A new message starts a new history point; an older undo or a pending
    // regeneration would rewrite it.
    setUndoRegeneration(null);
    setPendingRegeneration(null);
    setUndoEdit(null);
    setPendingEdit(null);
    setEditingMessageId(null);
    if (contentOverride === undefined) clearDraft(chat.id);

    await startGeneration(chat, started.assistantMessageId);
  }, [activeChat, beginTurn, cancelSpeech, clearDraft, draft, isGenerating, selectedModel, speechTranscript, startGeneration, streamRegistry]);

  const applyAndStartRegeneration = useCallback(async (chatId: string, plan: RegenerationPlan) => {
    // The store refuses a plan whose history no longer matches, so a stale
    // closure can never rewrite newer turns.
    if (!applyRegeneration(chatId, plan)) return;
    setUndoEdit(null);
    setPendingEdit(null);
    setEditingMessageId(null);
    setUndoRegeneration({
      chatId,
      messages: plan.previous,
      discarded: plan.discardedCount,
      // Undo is valid only while this exact placeholder is still the tail.
      appliedTailId: plan.assistantMessageId,
    });
    const currentChat = useChatStore.getState().chats[chatId];
    if (!currentChat) return;
    await startGeneration(currentChat, plan.assistantMessageId);
  }, [applyRegeneration, startGeneration]);

  const retryMessage = useCallback((assistantMessageId: string) => {
    const chat = activeChat;
    if (!chat || isGenerating || streamRegistry.get(chat.id)) return;
    // Reuse the original user turn: no duplicate user message is appended.
    const plan = planRegeneration(chat.id, assistantMessageId);
    if (!plan) return;
    if (plan.isLast) {
      void applyAndStartRegeneration(chat.id, plan);
      return;
    }
    // Older turn: every later message would be deleted, so confirm first.
    setPendingRegeneration({ chatId: chat.id, plan });
  }, [activeChat, applyAndStartRegeneration, isGenerating, planRegeneration, streamRegistry]);

  const undoLastRegeneration = useCallback(() => {
    if (!undoRegeneration || isGenerating) return;
    if (
      restoreMessages(
        undoRegeneration.chatId,
        undoRegeneration.messages,
        undoRegeneration.appliedTailId,
      )
    ) {
      setUndoRegeneration(null);
    }
  }, [isGenerating, restoreMessages, undoRegeneration]);



  const dropMetricsForIds = useCallback((ids: Iterable<string>) => {
    const idSet = new Set(ids);
    if (!idSet.size) return;
    setMetrics((prev) => {
      const next = { ...prev };
      idSet.forEach((id) => { delete next[id]; });
      return next;
    });
  }, []);

  const dropMetricsFor = useCallback((chatId: string) => {
    dropMetricsForIds(useChatStore.getState().chats[chatId]?.messages.map((m) => m.id) ?? []);
  }, [dropMetricsForIds]);

  const applyAndStartEdit = useCallback(async (chatId: string, plan: EditPlan) => {
    setEditingMessageId(null);
    setPendingEdit(null);
    // A newer send or regeneration makes its undo stale; never show two bars.
    setUndoRegeneration(null);
    setPendingRegeneration(null);
    if (!applyMessageEdit(chatId, plan)) return;
    const replacedIds = plan.replaced.map((m) => m.id);
    // Detach the replaced answer's telemetry before dropping it, so undo can
    // restore the answer's tokens, timings and processing card with its text.
    const metricsSnapshot: Record<string, ResponseMetrics> = {};
    for (const id of replacedIds) {
      const snapshot = metricsRef.current[id];
      if (snapshot) metricsSnapshot[id] = snapshot;
    }
    setUndoEdit({
      chatId,
      messages: plan.previous,
      discarded: plan.laterTurnCount,
      appliedTailId: plan.assistantMessageId,
      metrics: metricsSnapshot,
    });
    dropMetricsForIds(replacedIds);
    const currentChat = useChatStore.getState().chats[chatId];
    if (!currentChat) return;
    await startGeneration(currentChat, plan.assistantMessageId);
  }, [applyMessageEdit, dropMetricsForIds, startGeneration]);

  const requestMessageEdit = useCallback((messageId: string, content: string) => {
    const chat = activeChat;
    if (!chat || isGenerating) return;
    const next = content.trim();
    if (!next) return;
    const plan = planMessageEdit(chat.messages, messageId, next, {
      model: chat.model,
      provider: chat.model ? providerForKey(chat.model) : null,
    });
    if (!plan) return;
    // Replacing the current answer is expected and needs no warning. Only a
    // later conversation turn is actually removed, so confirm those.
    if (plan.laterTurnCount > 0) {
      setPendingEdit({ chatId: chat.id, plan });
      return;
    }
    void applyAndStartEdit(chat.id, plan);
  }, [activeChat, applyAndStartEdit, isGenerating]);

  const undoLastEdit = useCallback(() => {
    const undo = undoEdit;
    if (!undo || isGenerating) return;
    if (restoreMessages(undo.chatId, undo.messages, undo.appliedTailId)) {
      setMetrics((prev) => {
        const next = { ...prev };
        // The regenerated answer's telemetry is not part of the restored turn.
        delete next[undo.appliedTailId];
        return { ...next, ...undo.metrics };
      });
      setUndoEdit(null);
    }
  }, [isGenerating, restoreMessages, undoEdit]);

  const onDeleteChat = useCallback((chatId: string) => {
    stopChat(chatId);
    dropMetricsFor(chatId);
    deleteChat(chatId);
    // An undo from the deleted chat would resurrect removed history.
    setUndoRegeneration((prev) => (prev?.chatId === chatId ? null : prev));
    setPendingRegeneration((prev) => (prev?.chatId === chatId ? null : prev));
    setUndoEdit((prev) => (prev?.chatId === chatId ? null : prev));
    setEditingMessageId(null);
    setPendingEdit(null);
  }, [deleteChat, dropMetricsFor, stopChat]);

  const onClearChat = useCallback((chatId: string) => {
    stopChat(chatId);
    dropMetricsFor(chatId);
    clearChat(chatId);
    // Clearing is an explicit reset: it must not be undoable back to the old turns.
    setUndoRegeneration((prev) => (prev?.chatId === chatId ? null : prev));
    setPendingRegeneration((prev) => (prev?.chatId === chatId ? null : prev));
    setUndoEdit((prev) => (prev?.chatId === chatId ? null : prev));
    setEditingMessageId(null);
    setPendingEdit(null);
  }, [clearChat, dropMetricsFor, stopChat]);

  const onSelectChat = useCallback((chatId: string) => {
    selectChat(chatId);
    setEditingMessageId(null);
    setPendingEdit(null);
  }, [selectChat]);

  const onNewChat = useCallback(() => {
    createNewChat(activeChat?.model ?? pickDefaultModel(statusQuery.data?.models, null));
    setEditingMessageId(null);
    setPendingEdit(null);
  }, [activeChat?.model, createNewChat, statusQuery.data?.models]);

  // Provider reachability banners are rendered via shared <ChatProviderStatusBanners />.

  const scrollToBottom = () => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden p-0 m-0">
      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-transparent">
        <ChatTopBar
          title={<h1 className="truncate text-[15px] font-semibold tracking-tight text-foreground">Chat</h1>}
          activeMode={activeMode}
          temporaryEnabled={temporaryEnabled}
          persistentEnabled={persistentEnabled}
          onModeChange={onModeChange}
          model={selectedModel}
          contextInfo={contextInfo}
          contextOpen={contextOpen}
          onContextOpenChange={(open) => setOpenMenu(open ? 'context' : null)}
          onRefreshModels={() => { void statusQuery.refetch(); }}
          rightSlot={(
            <button
              type="button"
              onClick={() => activeChat && onClearChat(activeChat.id)}
              disabled={!activeChat || activeChat.messages.length === 0 || isGenerating}
              className="chat-ink inline-flex h-8 min-h-8 min-w-8 shrink-0 items-center justify-center gap-1.5 rounded-md px-2.5 text-xs transition hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
              title="Clear chat"
            >
              <Trash2Icon size={14} />
              <span className="hidden sm:inline">Clear</span>
            </button>
          )}
        />

        <ChatTabs
          chats={chats}
          activeId={activeId}
          canCreate={canCreate}
          generatingChatIds={Object.keys(streaming)}
          panelIdBase={panelIdBase}
          onSelect={onSelectChat}
          onNew={onNewChat}
          onDelete={onDeleteChat}
          onStop={stopChat}
        />

        <div
          id={activeIndex >= 0 ? `${panelIdBase}-panel-${activeIndex}` : undefined}
          role="tabpanel"
          aria-label={activeChat?.title || 'Chat conversation'}
          ref={listRef}
          className={`relative z-10 min-h-0 flex-1 ${isFreshChat ? 'overflow-hidden max-[520px]:overflow-y-auto' : 'overflow-y-auto'} overscroll-contain bg-transparent px-3 py-6 md:px-6`}
        >
          <ChatProviderStatusBanners catalog={statusQuery.data} />
          {!activeChat || activeChat.messages.length === 0 ? (
            <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center text-center">
              <div className="max-w-md px-4">
                <div className="flex items-center justify-center gap-5 mb-8 md:gap-6 md:mb-10">
                  <div className="flex items-center gap-3 md:gap-4">
                    <Image
                      src="/revora-logo.png"
                      alt="Revora"
                      width={48}
                      height={48}
                      style={{ width: 48, height: 48 }}
                      className="rounded-xl object-contain shrink-0 md:w-16 md:h-16"
                    />
                    <span
                      className="font-bold text-2xl tracking-tight text-foreground font-heading md:text-3xl"
                      style={{ fontFamily: 'var(--font-oxanium, inherit)' }}
                    >
                      Revora
                    </span>
                  </div>
                  <span className="inline-flex items-center justify-center w-8 h-8 rounded-full text-xl font-light backdrop-blur-sm text-muted-foreground/70 bg-muted/40 border border-border/50 dark:text-slate-100 dark:bg-white/10 dark:border-white/15 md:w-10 md:h-10 md:text-2xl" aria-hidden>×</span>
                  <div className="flex items-center gap-3 md:gap-4">
                    <Image
                      src="/assets/kllm.svg"
                      alt="kLLM"
                      width={42}
                      height={42}
                      style={{ width: 42, height: 42 }}
                      className="rounded-lg shrink-0 md:w-14 md:h-14"
                    />
                    <span className="font-bold text-2xl tracking-tight text-foreground md:text-3xl">kLLM</span>
                    <ManagedByRevora size="xs" className="shrink-0" />
                  </div>
                </div>
                <p className="text-xl font-medium tracking-tight text-foreground">What can I help with?</p>
                <p className="chat-ink mt-2 text-sm leading-6">
                  Temporary in-memory chat. Messages are cleared on refresh, close, logout, or account change.
                </p>
                {!statusQuery.data?.models?.some(isModelSelectable) && statusQuery.data?.enabled ? (
                  <p className="mt-3 text-sm text-warning">
                    No model is loaded right now. Chat unlocks when an administrator loads one.
                  </p>
                ) : null}
              </div>
            </div>
          ) : (
            <ChatMessageList
              messages={activeChat.messages}
              metrics={metrics}
              activeStreamMessageId={activeStreamMessageId}
              thinking={isThinking}
              thinkingOrbRef={thinkingOrbRef}
              canRegenerate={!isGenerating}
              canEdit={!isGenerating}
              editingMessageId={editingMessageId}
              onRetry={retryMessage}
              onRegenerate={(message) => retryMessage(message.id)}
              onBeginEdit={(id) => setEditingMessageId(id)}
              onCancelEdit={() => setEditingMessageId(null)}
              onEdit={requestMessageEdit}
            />
          )}
        </div>

        {undoRegeneration && undoRegeneration.chatId === activeId ? (
          <div className="relative z-20 mx-auto flex w-full max-w-3xl items-center justify-between gap-3 px-3 pb-2 md:px-6">
            <p className="chat-ink text-xs">{undoNotice(undoRegeneration.discarded)}</p>
            <button
              type="button"
              onClick={undoLastRegeneration}
              disabled={isGenerating}
              className="inline-flex h-8 shrink-0 items-center rounded-md border border-border/80 px-3 text-xs font-medium text-foreground transition hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-45"
            >
              Undo
            </button>
          </div>
        ) : null}

        {undoEdit && undoEdit.chatId === activeId ? (
          <div className="relative z-20 mx-auto flex w-full max-w-3xl items-center justify-between gap-3 px-3 pb-2 md:px-6">
            <p className="chat-ink text-xs">{editUndoNotice(undoEdit.discarded)}</p>
            <button
              type="button"
              onClick={undoLastEdit}
              disabled={isGenerating}
              className="inline-flex h-8 shrink-0 items-center rounded-md border border-border/80 px-3 text-xs font-medium text-foreground transition hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-45"
            >
              Undo
            </button>
          </div>
        ) : null}

        {showScrollButton ? (
          <button
            type="button"
            onClick={scrollToBottom}
            className="chat-ink absolute bottom-[calc(96px+env(safe-area-inset-bottom))] left-1/2 z-20 inline-flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-border/70 bg-background/90 shadow-sm backdrop-blur transition hover:bg-muted hover:text-foreground md:bottom-[104px]"
            aria-label="Scroll to bottom"
            title="Scroll to bottom"
          >
            <ArrowDownIcon size={16} />
          </button>
        ) : null}

        <ChatComposer
          value={speechTranscript ?? draft}
          disabled={!!disabledReason || !activeChat}
          sending={isGenerating}
          canStop={isGenerating}
          helperText={sendError ?? disabledReason}
          modelStatus={statusQuery.data}
          modelValue={activeChat?.model ?? null}
          reasoningEffort={reasoningEffort}
          onReasoningEffortChange={setReasoningEffort}
          onModelChange={(model) => activeChat && setChatModel(activeChat.id, model)}
          onChange={(value) => {
            if (activeChat) setDraftValue(activeChat.id, value);
            setSpeechTranscript(null);
            // A new keystroke invalidates the previous refusal message.
            if (sendError) setSendError(null);
          }}
          onSend={() => void sendMessage()}
          onStop={() => activeChat && stopChat(activeChat.id)}
          generationPhase={beamGenerationPhase}
          openMenu={openMenu}
          onOpenMenuChange={setOpenMenu}
          caretRequest={speechInsertToken}
          speech={
            speechEnabled
              ? {
                  enabled: true,
                  phase: speech.phase,
                  error: speech.error,
                  readiness: speechReadiness,
                  elapsedMs: speech.elapsedMs,
                  maxSeconds: speech.maxSeconds,
                  onStart: speech.start,
                  onStop: speech.stop,
                  onCancel: speech.cancel,
                }
              : undefined
          }
        />
        <ConfirmDialog
          open={pendingRegeneration !== null}
          title="Regenerate this response?"
          description={
            pendingRegeneration
              ? regenerationPrompt(pendingRegeneration.plan.discardedCount)
              : ''
          }
          confirmLabel="Regenerate"
          busy={isGenerating}
          onCancel={() => setPendingRegeneration(null)}
          onConfirm={() => {
            const pending = pendingRegeneration;
            if (!pending) return;
            setPendingRegeneration(null);
            void applyAndStartRegeneration(pending.chatId, pending.plan);
          }}
        />
        <ConfirmDialog
          open={pendingEdit !== null}
          title="Edit this message?"
          description={pendingEdit ? editPrompt(pendingEdit.plan.laterTurnCount) : ''}
          confirmLabel="Save & Send"
          busy={isGenerating}
          onCancel={() => {
            setPendingEdit(null);
            setEditingMessageId(null);
          }}
          onConfirm={() => {
            const pending = pendingEdit;
            if (!pending) return;
            void applyAndStartEdit(pending.chatId, pending.plan);
          }}
        />
      </section>
    </div>
  );
}
