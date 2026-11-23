'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDownIcon, ChevronDownIcon, RefreshCwIcon, Trash2Icon } from 'lucide-react';

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
  CHAT_MAX_MESSAGES_PER_CHAT,
  TRUNCATION_MESSAGE,
  buildChatContext,
  coalesceMetricsPatch,
  computeContextUsed,
  computeTokensPerSecond,
  isModelSelectable,
  isTruncatedFinish,
  pickDefaultModel,
  type ResponseMetrics,
  type ResponsePhase,
  type TemporaryChat,
} from '@/lib/chat-state';
import { usePlatformFeatures, isFeatureEnabled } from '@/lib/use-platform-features';
import { useAuthStore } from '@/store/useAuthStore';
import { useChatStore } from '@/store/useChatStore';

import Image from 'next/image';
import ThinkingOrb from '@/components/ui/ai-thiking-orb-and-input';
import { ChatComposer } from './chat-composer';
import { ChatTabs } from './chat-tabs';
import { MessageBubble } from './message-bubble';

const SCROLL_NEAR_BOTTOM_PX = 80;

type ChatMenu = 'context' | 'model' | 'effort' | null;

export function ChatShell({ onKllmStatusChange }: { onKllmStatusChange?: (unavailable: boolean) => void } = {}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: features } = usePlatformFeatures();
  const chatFlagEnabled = isFeatureEnabled(features, 'chat');

  const activeId = useChatStore((s) => s.activeId);
  const chatsRecord = useChatStore((s) => s.chats);
  const order = useChatStore((s) => s.order);
  const ensureActiveChat = useChatStore((s) => s.ensureActiveChat);
  const createNewChat = useChatStore((s) => s.createNewChat);
  const selectChat = useChatStore((s) => s.selectChat);
  const deleteChat = useChatStore((s) => s.deleteChat);
  const clearChat = useChatStore((s) => s.clearChat);
  const setChatModel = useChatStore((s) => s.setChatModel);
  const appendUserMessage = useChatStore((s) => s.appendUserMessage);
  const startAssistantMessage = useChatStore((s) => s.startAssistantMessage);
  const appendAssistantDelta = useChatStore((s) => s.appendAssistantDelta);
  const finishAssistantMessage = useChatStore((s) => s.finishAssistantMessage);
  const prepareRetry = useChatStore((s) => s.prepareRetry);
  const resetAll = useChatStore((s) => s.resetAll);

  const [draft, setDraft] = useState('');
  const [activeStream, setActiveStream] = useState<{ chatId: string; messageId: string } | null>(null);
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>('medium');
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [openMenu, setOpenMenu] = useState<ChatMenu>(null);
  const [metrics, setMetrics] = useState<Record<string, ResponseMetrics>>({});
  // Random chat ids are generated in the in-memory store at module init, so they
  // differ between SSR and hydration. Derive DOM ids from a stable useId base instead.
  const panelIdBase = useId();
  const abortRef = useRef<AbortController | null>(null);
  const streamChatRef = useRef<string | null>(null);
  const streamMsgRef = useRef<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const flushFrameRef = useRef<number | null>(null);
  const pendingDeltaRef = useRef('');
  const pendingMetricsRef = useRef<{
    messageId: string;
    patch: Partial<ResponseMetrics>;
  } | null>(null);
  const contextRef = useRef<HTMLDivElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const thinkingOrbRef = useRef<HTMLDivElement | null>(null);

  const contextOpen = openMenu === 'context';

  const chats = useMemo(() => order.map((id) => chatsRecord[id]).filter(Boolean), [order, chatsRecord]);
  const activeChat = activeId ? chatsRecord[activeId] ?? null : null;
  const activeIndex = chats.findIndex((c) => c?.id === activeId);
  const isFreshChat = !activeChat || activeChat.messages.length === 0;

  const statusQuery = useQuery({
    queryKey: ['kllm', 'status', 'chat'],
    queryFn: ({ signal }) => api.getKllmStatus(signal),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: 1,
    enabled: chatFlagEnabled,
  });

  // Notify parent when kLLM status becomes unavailable/stale so the
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

  useEffect(() => {
    ensureActiveChat();
  }, [ensureActiveChat]);

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

  useEffect(() => {
    if (!contextOpen) return;
    const onPointer = (e: MouseEvent) => {
      if (!contextRef.current?.contains(e.target as Node)) setOpenMenu(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpenMenu(null);
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [contextOpen]);

  // Mobile-only: position the Context popover with fixed positioning so it
  // spans the viewport width minus safe margins instead of clipping off the
  // left edge. Uses direct DOM manipulation (via ref) to avoid synchronous
  // setState in the effect body. Resets inline styles on desktop.
  useEffect(() => {
    if (!contextOpen || !contextRef.current || !popoverRef.current) return;
    const applyPosition = () => {
      if (!contextRef.current || !popoverRef.current) return;
      const isMobile = window.innerWidth < 640;
      if (isMobile) {
        const rect = contextRef.current.getBoundingClientRect();
        popoverRef.current.style.position = 'fixed';
        popoverRef.current.style.top = `${rect.bottom + 8}px`;
        popoverRef.current.style.left = '12px';
        popoverRef.current.style.right = '12px';
        popoverRef.current.style.width = 'auto';
        popoverRef.current.style.maxWidth = 'none';
      } else {
        popoverRef.current.style.position = '';
        popoverRef.current.style.top = '';
        popoverRef.current.style.left = '';
        popoverRef.current.style.right = '';
        popoverRef.current.style.width = '';
        popoverRef.current.style.maxWidth = '';
      }
    };
    applyPosition();
    window.addEventListener('resize', applyPosition);
    return () => window.removeEventListener('resize', applyPosition);
  }, [contextOpen]);

  useEffect(() => {
    const el = listRef.current;
    if (!el || !stickToBottomRef.current || isFreshChat) return;
    el.scrollTop = el.scrollHeight;
  }, [activeChat?.messages, activeStream, activeId, isFreshChat]);

  // One flush per animation frame carries BOTH the accumulated text and the
  // latest telemetry. Previously timings_per_token produced a setState per token
  // (plus one for the chunk model), starving the main thread so the answer was
  // only painted after generation ended.
  const flushPending = useCallback(() => {
    const chatId = streamChatRef.current;
    const messageId = streamMsgRef.current;
    const delta = pendingDeltaRef.current;
    if (chatId && messageId && delta) {
      pendingDeltaRef.current = '';
      appendAssistantDelta(chatId, messageId, delta);
    }
    const pending = pendingMetricsRef.current;
    if (pending) {
      pendingMetricsRef.current = null;
      setMetrics((prev) => ({
        ...prev,
        [pending.messageId]: {
          ...(prev[pending.messageId] ?? {
            phase: 'preparing' as ResponsePhase,
            startedAt: performance.now(),
          }),
          ...pending.patch,
        },
      }));
    }
  }, [appendAssistantDelta]);

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
    pendingMetricsRef.current = coalesceMetricsPatch(
      pendingMetricsRef.current,
      messageId,
      patch,
    );
    scheduleFrame();
  }, [scheduleFrame]);

  useEffect(() => {
    return () => {
      cancelFrame();
      abortRef.current?.abort();
    };
  }, [cancelFrame]);

  const isGenerating = activeStream !== null;
  const thinkingMessage = activeStream
    ? chatsRecord[activeStream.chatId]?.messages.find((m) => m.id === activeStream.messageId)
    : undefined;
  const isThinking = !!activeStream && !thinkingMessage?.content?.trim();

  useEffect(() => {
    if (isFreshChat && listRef.current) {
      listRef.current.scrollTop = 0;
      setShowScrollButton(false);
    }
  }, [isFreshChat]);

  useEffect(() => {
    if (!isThinking || !thinkingOrbRef.current || !listRef.current) return;
    const el = listRef.current;
    const orb = thinkingOrbRef.current;
    const orbTop = orb.offsetTop;
    const targetScroll = orbTop - el.clientHeight / 2 + orb.clientHeight / 2;
    el.scrollTo({ top: Math.max(0, targetScroll), behavior: 'smooth' });
  }, [isThinking]);

  const selectedModel = useMemo(() => {
    const modelKey = activeChat?.model;
    if (!modelKey) return null;
    return statusQuery.data?.models?.find((m) => m.key === modelKey) ?? null;
  }, [activeChat, statusQuery.data?.models]);

  const activeMetrics = activeStream
    ? metrics[activeStream.messageId]
    : activeChat?.messages.length
      ? metrics[activeChat.messages[activeChat.messages.length - 1]?.id ?? '']
      : undefined;
  const beamGenerationPhase: 'preparing' | 'thinking' | 'generating' | null = !activeStream
    ? null
    : activeMetrics?.phase === 'generating'
      ? 'generating'
      : activeMetrics?.phase === 'thinking'
        ? 'thinking'
        : 'preparing';

  const contextInfo = useMemo(() => {
    const ctx = buildChatContext(activeChat);
    const approxTokens = Math.ceil(ctx.reduce((s, m) => s + m.content.length, 0) / 4);
    const backendUsed = activeMetrics?.contextUsed;
    const contextWindow = activeMetrics?.contextTotal ?? selectedModel?.context_window ?? null;
    const usedTokens = backendUsed ?? approxTokens;
    const usedPct =
      contextWindow && contextWindow > 0
        ? Math.min(100, Math.round((usedTokens / contextWindow) * 100))
        : null;
    const remaining = contextWindow ? Math.max(0, contextWindow - usedTokens) : null;
    return {
      approxTokens,
      usedTokens,
      contextWindow,
      usedPct,
      remaining,
      messages: ctx.length,
      backendBacked: backendUsed !== undefined,
    };
  }, [activeChat, selectedModel, activeMetrics]);

  const selectedModelReady = isModelSelectable(selectedModel);
  const kllmReady = !!statusQuery.data?.enabled && !!statusQuery.data?.reachable && !statusQuery.data?.stale;
  const canCreate = order.length < CHAT_MAX_CHATS;
  const atMessageLimit = (activeChat?.messages.length ?? 0) >= CHAT_MAX_MESSAGES_PER_CHAT;

  const disabledReason = useMemo(() => {
    if (!chatFlagEnabled) return null;
    if (isGenerating) return 'A response is already being generated. Stop it before sending another message.';
    if (!activeChat) return 'Create a chat to begin.';
    if (!statusQuery.data) return statusQuery.isLoading ? 'Loading kLLM status...' : null;
    if (!statusQuery.data.enabled) return 'kLLM is unavailable. Ask an administrator to enable it.';
    if (!statusQuery.data.reachable || statusQuery.data.stale) return 'kLLM status is unavailable or stale. Refresh and try again.';
    if (!activeChat.model) return 'Select a ready model to start chatting.';
    if (!selectedModelReady) return 'The selected model is not ready. Choose another ready model.';
    if (atMessageLimit) return 'This temporary chat is full. Start a new chat.';
    return null;
  }, [activeChat, atMessageLimit, chatFlagEnabled, isGenerating, selectedModelReady, statusQuery.data, statusQuery.isLoading]);

  const handleAuthError = useCallback(async () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setActiveStream(null);
    resetAll();
    await useAuthStore.getState().logout({ revoke: false });
    router.replace('/login');
  }, [resetAll, router]);

  const stopActive = useCallback(() => {
    const chatId = streamChatRef.current;
    const messageId = streamMsgRef.current;
    flushNow();
    abortRef.current?.abort();
    abortRef.current = null;
    if (chatId && messageId) {
      finishAssistantMessage(chatId, messageId, 'stopped');
      queueMetrics(messageId, { phase: 'stopped', endedAt: performance.now() });
      flushNow();
    }
    streamChatRef.current = null;
    streamMsgRef.current = null;
    setActiveStream(null);
  }, [finishAssistantMessage, flushNow, queueMetrics]);

  const startGeneration = useCallback(async (
    chat: TemporaryChat,
    assistantMessageId: string,
  ) => {
    if (!chat.model) return;
    const context = buildChatContext(useChatStore.getState().chats[chat.id]);
    if (context.length === 0) {
      finishAssistantMessage(chat.id, assistantMessageId, 'error', 'A valid user message is required.');
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    streamChatRef.current = chat.id;
    streamMsgRef.current = assistantMessageId;
    pendingDeltaRef.current = '';
    setActiveStream({ chatId: chat.id, messageId: assistantMessageId });
    stickToBottomRef.current = true;
    queueMetrics(assistantMessageId, {
      phase: 'preparing',
      startedAt: performance.now(),
      contextTotal: selectedModel?.context_window ?? undefined,
    });
    flushNow();

    let finalFinishReason: string | null | undefined;
    let receivedDelta = false;

    const guarded = (fn: () => void) => {
      if (streamChatRef.current !== chat.id || streamMsgRef.current !== assistantMessageId) return;
      fn();
    };

    const finishWithReason = (reason?: string | null) => {
      const truncated = isTruncatedFinish(reason);
      finishAssistantMessage(
        chat.id,
        assistantMessageId,
        truncated ? 'error' : 'complete',
        truncated ? TRUNCATION_MESSAGE : undefined,
      );
      queueMetrics(assistantMessageId, {
        phase: truncated ? 'truncated' : 'complete',
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
        { model: chat.model, messages: context, stream: true, reasoning_effort: reasoningEffort },
        {
          onDelta: (delta) => guarded(() => {
            if (!receivedDelta) {
              receivedDelta = true;
              queueMetrics(assistantMessageId, { phase: 'generating' });
            }
            pendingDeltaRef.current += delta;
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
            if (event.name) queueMetrics(assistantMessageId, { model: event.name });
          }),
        },
        controller.signal,
      );
      if (!hadError) {
        guarded(() => {
          const current = useChatStore.getState().chats[chat.id]?.messages.find((m) => m.id === assistantMessageId);
          if (current?.status === 'streaming') {
            flushNow();
            finishWithReason(finalFinishReason);
          }
        });
      }
    } catch (error) {
      if ((error as Error)?.name === 'AbortError') return;
      if (error instanceof ChatAuthError) {
        await handleAuthError();
        return;
      }
      const message = error instanceof ChatRequestError ? error.message : 'Chat request failed. Please try again.';
      finishAssistantMessage(chat.id, assistantMessageId, 'error', message);
      queueMetrics(assistantMessageId, { phase: 'error', endedAt: performance.now() });
      flushNow();
      if (error instanceof ChatRequestError && error.status === 503) {
        void queryClient.invalidateQueries({ queryKey: ['kllm', 'status'] });
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (streamChatRef.current === chat.id && streamMsgRef.current === assistantMessageId) {
        streamChatRef.current = null;
        streamMsgRef.current = null;
        setActiveStream(null);
      }
    }
  }, [finishAssistantMessage, flushNow, handleAuthError, queryClient, queueMetrics, reasoningEffort, scheduleFrame, selectedModel]);

  const sendMessage = useCallback(async (contentOverride?: string) => {
    const chat = activeChat;
    const content = (contentOverride ?? draft).trim();
    if (!chat || !content || isGenerating) return;
    if (!chat.model || !isModelSelectable(selectedModel) || !kllmReady) return;
    if (chat.messages.length >= CHAT_MAX_MESSAGES_PER_CHAT) return;

    const userMessageId = appendUserMessage(chat.id, content);
    if (!userMessageId) return;
    if (contentOverride === undefined) setDraft('');

    const assistantMessageId = startAssistantMessage(chat.id);
    if (!assistantMessageId) return;

    await startGeneration(chat, assistantMessageId);
  }, [activeChat, appendUserMessage, draft, isGenerating, kllmReady, selectedModel, startAssistantMessage, startGeneration]);

  const retryMessage = useCallback(async (assistantMessageId: string) => {
    const chat = activeChat;
    if (!chat || isGenerating) return;
    // Reuse the original user turn: no duplicate user message is appended.
    const prepared = prepareRetry(chat.id, assistantMessageId);
    if (!prepared) return;
    const currentChat = useChatStore.getState().chats[chat.id];
    if (!currentChat) return;
    await startGeneration(currentChat, prepared.assistantMessageId);
  }, [activeChat, isGenerating, prepareRetry, startGeneration]);

  const dropMetricsFor = useCallback((chatId: string) => {
    const ids = new Set(useChatStore.getState().chats[chatId]?.messages.map((m) => m.id) ?? []);
    if (!ids.size) return;
    setMetrics((prev) => {
      const next = { ...prev };
      ids.forEach((id) => { delete next[id]; });
      return next;
    });
  }, []);

  const onDeleteChat = useCallback((chatId: string) => {
    if (streamChatRef.current === chatId) stopActive();
    dropMetricsFor(chatId);
    deleteChat(chatId);
  }, [deleteChat, dropMetricsFor, stopActive]);

  const onClearChat = useCallback((chatId: string) => {
    if (streamChatRef.current === chatId) stopActive();
    dropMetricsFor(chatId);
    clearChat(chatId);
  }, [clearChat, dropMetricsFor, stopActive]);

  const statusBanner = (() => {
    if (!statusQuery.data) return null;
    if (!statusQuery.data.enabled) {
      return <div className="mx-auto mb-4 max-w-3xl rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning dark:bg-zinc-950/80 dark:border-amber-400/35 dark:text-amber-200 dark:backdrop-blur-md">Chat needs kLLM. Ask an administrator to enable it.</div>;
    }
    if (!statusQuery.data.reachable || statusQuery.data.stale) {
      return <div className="mx-auto mb-4 max-w-3xl rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning dark:bg-zinc-950/80 dark:border-amber-400/35 dark:text-amber-200 dark:backdrop-blur-md">kLLM status is unavailable or stale. Refresh before sending.</div>;
    }
    return null;
  })();

  const scrollToBottom = () => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden p-0 m-0">
      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-transparent">
        <div className="w-full shrink-0 relative z-30 border-b border-border/60 bg-background/85 py-2.5 backdrop-blur-md">
          <div className="flex w-full items-center justify-between gap-3 px-4 md:px-6">
            <div className="min-w-0 flex items-center gap-2">
              <h1 className="truncate text-[15px] font-semibold tracking-tight text-foreground">Chat</h1>
              <span className="chat-ink hidden text-xs sm:inline">Temporary</span>
              {selectedModel ? (
                <span className="chat-ink hidden max-w-[220px] truncate rounded-full border border-border/70 bg-surface-2/70 px-2 py-0.5 text-[11px] md:inline-flex">
                  {selectedModel.key}
                </span>
              ) : null}
            </div>

            <div className="flex items-center gap-1.5">
              <div className="relative" ref={contextRef}>
                <button
                  type="button"
                  onClick={() => setOpenMenu(contextOpen ? null : 'context')}
                  className="chat-ink inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs transition hover:bg-muted/60 hover:text-foreground"
                  aria-label="Context information"
                  aria-expanded={contextOpen}
                  title="Context information"
                >
                  <span>Context</span>
                  {contextInfo.usedPct !== null ? <span className="chat-ink tabular-nums">{contextInfo.usedPct}%</span> : null}
                  <ChevronDownIcon size={13} className={`transition ${contextOpen ? 'rotate-180' : ''}`} />
                </button>
                {contextOpen ? (
                  <div
                    ref={popoverRef}
                    className="absolute right-0 top-full z-50 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-popover px-4 py-3.5 text-popover-foreground shadow-xl sm:w-[340px]"
                  >
                    <div className="flex items-center justify-between gap-3 text-xs min-w-0">
                      <span className="font-semibold text-foreground min-w-0 truncate">Context</span>
                      <span className="tabular-nums text-muted-foreground min-w-0 truncate">
                        {contextInfo.contextWindow
                          ? `${contextInfo.usedTokens.toLocaleString()} / ${contextInfo.contextWindow.toLocaleString()}`
                          : `${contextInfo.usedTokens.toLocaleString()}${contextInfo.backendBacked ? '' : ' est.'} tokens`}
                      </span>
                    </div>
                    {contextInfo.contextWindow ? (
                      <>
                        <div className="my-3 h-2 w-full overflow-hidden rounded-full bg-muted">
                          <div className="h-full rounded-full bg-brand transition-[width] duration-300" style={{ width: `${contextInfo.usedPct ?? 0}%` }} />
                        </div>
                        <div className="grid grid-cols-2 gap-4 min-w-0">
                          <div className="min-w-0">
                            <span className="block text-sm font-semibold tabular-nums text-foreground">{contextInfo.usedPct}%</span>
                            <span className="text-xs text-muted-foreground">used</span>
                          </div>
                          <div className="min-w-0 text-right">
                            <span className="block text-sm font-semibold tabular-nums text-foreground truncate">{contextInfo.remaining?.toLocaleString()}</span>
                            <span className="text-xs text-muted-foreground">remaining</span>
                          </div>
                        </div>
                      </>
                    ) : (
                      <p className="my-3 text-xs leading-relaxed text-muted-foreground">Model context window is not reported by the gateway.</p>
                    )}
                    <div className="my-3 border-t border-border/70" />
                    <div className="space-y-1 text-xs min-w-0">
                      <div className="flex items-center justify-between gap-4 py-1 flex-wrap">
                        <span className="text-muted-foreground min-w-0">Messages in context</span>
                        <span className="font-medium tabular-nums text-foreground min-w-0">{contextInfo.messages}</span>
                      </div>
                      <div className="flex items-center justify-between gap-4 py-1 flex-wrap">
                        <span className="text-muted-foreground min-w-0">Source</span>
                        <span className="font-medium text-foreground min-w-0">
                          {contextInfo.backendBacked ? 'Backend timings' : '~4 chars/token estimate'}
                        </span>
                      </div>
                    </div>
                    <p className="mt-3 border-t border-border/50 pt-2.5 text-xs leading-relaxed text-muted-foreground">
                      {contextInfo.backendBacked
                        ? 'From live llama-server timings: new prompt + cached + generated tokens.'
                        : 'Approximate from current message text; live timings arrive once generation starts.'}
                    </p>
                  </div>
                ) : null}
              </div>

              <button
                type="button"
                onClick={() => activeChat && onClearChat(activeChat.id)}
                disabled={!activeChat || activeChat.messages.length === 0 || isGenerating}
                className="chat-ink inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs transition hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
                title="Clear chat"
              >
                <Trash2Icon size={14} />
                <span className="hidden sm:inline">Clear</span>
              </button>
              <button
                type="button"
                onClick={() => statusQuery.refetch()}
                className="chat-ink inline-flex h-8 w-8 items-center justify-center rounded-md transition hover:bg-muted/60 hover:text-foreground"
                aria-label="Refresh kLLM status"
                title="Refresh kLLM status"
              >
                <RefreshCwIcon size={14} />
              </button>
            </div>
          </div>
        </div>

        <ChatTabs
          chats={chats}
          activeId={activeId}
          canCreate={canCreate}
          isGenerating={isGenerating}
          panelIdBase={panelIdBase}
          onSelect={selectChat}
          onNew={() => createNewChat(activeChat?.model ?? pickDefaultModel(statusQuery.data?.models, null))}
          onDelete={onDeleteChat}
          onStop={stopActive}
        />

        <div
          id={activeIndex >= 0 ? `${panelIdBase}-panel-${activeIndex}` : undefined}
          role="tabpanel"
          aria-label={activeChat?.title || 'Chat conversation'}
          ref={listRef}
          className={`relative z-10 min-h-0 flex-1 ${isFreshChat ? 'overflow-hidden' : 'overflow-y-auto'} overscroll-contain bg-transparent px-3 py-6 md:px-6`}
        >
          {statusBanner}
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
            <div className="mx-auto flex max-w-3xl flex-col gap-8 pb-4">
              {activeChat.messages.map((message) => {
                // The orb replaces the empty streaming placeholder until real
                // content arrives; avoid a duplicate blinking cursor bubble.
                const isAssistantPlaceholder =
                  message.role === 'assistant' &&
                  message.id === activeStream?.messageId &&
                  !message.content?.trim();
                if (isAssistantPlaceholder && isThinking) {
                  return (
                    <div
                      key={message.id}
                      ref={thinkingOrbRef}
                      className="py-8 flex flex-col items-center justify-center"
                    >
                      <ThinkingOrb active={isThinking} size={132} />
                    </div>
                  );
                }
                if (isAssistantPlaceholder) return null;
                return (
                  <MessageBubble
                    key={message.id}
                    message={message}
                    metrics={metrics[message.id]}
                    onRetry={message.status === 'error' ? () => retryMessage(message.id) : undefined}
                    onRegenerate={message.role === 'assistant' && message.status !== 'streaming' ? () => retryMessage(message.id) : undefined}
                    canRegenerate={!isGenerating}
                  />
                );
              })}
            </div>
          )}
        </div>

        {showScrollButton ? (
          <button
            type="button"
            onClick={scrollToBottom}
            className="chat-ink absolute bottom-[104px] left-1/2 z-20 inline-flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-border/70 bg-background/90 shadow-sm backdrop-blur transition hover:bg-muted hover:text-foreground"
            aria-label="Scroll to bottom"
            title="Scroll to bottom"
          >
            <ArrowDownIcon size={16} />
          </button>
        ) : null}

        <ChatComposer
          value={draft}
          disabled={!!disabledReason || !activeChat}
          sending={isGenerating}
          canStop={isGenerating}
          helperText={disabledReason}
          modelStatus={statusQuery.data}
          modelValue={activeChat?.model ?? null}
          reasoningEffort={reasoningEffort}
          onReasoningEffortChange={setReasoningEffort}
          onModelChange={(model) => activeChat && setChatModel(activeChat.id, model)}
          onChange={setDraft}
          onSend={() => void sendMessage()}
          onStop={stopActive}
          generationPhase={beamGenerationPhase}
          openMenu={openMenu}
          onOpenMenuChange={setOpenMenu}
        />
      </section>
    </div>
  );
}
