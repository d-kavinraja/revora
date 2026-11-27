'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, MessageCircle, Pencil, Plus, Trash2, X } from 'lucide-react';
import { api, type PersistentChatMessage } from '@/lib/api';
import { streamPersistentTurn } from '@/lib/persistent-chat-api';
import {
  CHAT_MAX_MESSAGE_CHARS,
  computeContextUsed,
  isModelSelectable,
  nextRequestContextMeter,
  turnProvenance,
  visibleChatModels,
  withPendingChatDraft,
  type ChatMessage,
  type ResponseMetrics,
  type TemporaryChat,
} from '@/lib/chat-state';
import { formatSpeechError, insertTranscript } from '@/lib/speech';
import type { ReasoningEffort } from '@/lib/chat-api';
import {
  activityLabelFor,
  mergeBackendStatus,
  type LiveChatActivity,
} from '@/lib/chat-activity';
import { ChatComposer } from './chat-composer';
import { ChatMessageList } from './chat-message-list';
import { PersistentChatTabs } from './persistent-chat-tabs';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { useToast } from '@/components/ui/toaster';
import { ChatTopBar } from './chat-top-bar';
import { useSpeechToText } from './use-speech-to-text';

function currentTime(): number {
  return Date.now();
}

function toChatMessage(message: PersistentChatMessage): ChatMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    status: message.status as ChatMessage['status'],
    createdAt: new Date(message.created_at).getTime(),
    model: message.model,
    finishReason: message.finish_reason,
  };
}

interface PersistentChatShellProps {
  enabled: boolean;
  activeMode?: 'temporary' | 'persistent';
  temporaryEnabled?: boolean;
  persistentEnabled?: boolean;
  onModeChange?: (mode: 'temporary' | 'persistent') => void;
  isActive?: boolean;
  onKllmStatusChange?: (unavailable: boolean) => void;
}

export function PersistentChatShell({
  enabled,
  activeMode = 'persistent',
  temporaryEnabled = false,
  persistentEnabled = enabled,
  onModeChange,
  isActive = true,
  onKllmStatusChange,
}: PersistentChatShellProps) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const draft = drafts[activeId ?? 'new'] ?? '';
  const [speechTranscript, setSpeechTranscript] = useState<string | null>(null);
  const [prevActiveId, setPrevActiveId] = useState<string | null>(activeId);
  if (activeId !== prevActiveId) {
    setPrevActiveId(activeId);
    setSpeechTranscript(null);
  }
  const setDraft = useCallback((value: string, chatId = activeId ?? 'new') => {
    setDrafts((current) => ({ ...current, [chatId]: value }));
  }, [activeId]);
  const [localMessages, setLocalMessages] = useState<Record<string, ChatMessage[]>>({});
  const [busyChats, setBusyChats] = useState<Record<string, true>>({});
  const [metrics, setMetrics] = useState<Record<string, ResponseMetrics>>({});
  const [activityClock, setActivityClock] = useState(() => Date.now());
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState('');
  const [modelByConversation, setModelByConversation] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>('medium');
  const [openMenu, setOpenMenu] = useState<'context' | 'model' | 'effort' | null>(null);
  const contextOpen = openMenu === 'context';
  const [speechInsertToken, setSpeechInsertToken] = useState(0);
  const [confirm, setConfirm] = useState<{ message: ChatMessage; kind: 'edit' | 'regenerate'; content?: string } | null>(null);
  const controllersRef = useRef(new Map<string, AbortController>());
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const thinkingOrbRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  // Per-conversation activity survives generic thinking frames and keeps
  // simultaneous requests isolated. It is cleared in the stream's finally.
  const [activityByChat, setActivityByChat] = useState<Record<string, LiveChatActivity>>({});

  const conversations = useQuery({
    queryKey: ['persistent-chat', 'conversations'],
    queryFn: api.listPersistentChats,
    refetchInterval: 15_000,
    retry: false,
    enabled: isActive,
  });
  const conversation = useQuery({
    queryKey: ['persistent-chat', 'conversation', activeId],
    queryFn: () => api.getPersistentChat(activeId!),
    enabled: isActive && !!activeId,
    retry: false,
  });
  const speechStatus = useQuery({
    queryKey: ['speech', 'status'],
    queryFn: ({ signal }) => api.getSpeechStatus(signal),
    staleTime: 0,
    refetchInterval: (query) => (query.state.data?.state && query.state.data.state !== 'ready' ? 5_000 : 15_000),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: 0,
    enabled: isActive,
  });
  const catalog = useQuery({
    queryKey: ['chat', 'models'],
    queryFn: ({ signal }) => api.getChatModels(signal),
    staleTime: 15_000,
    retry: 1,
    enabled: isActive,
  });

  useEffect(() => {
    if (!onKllmStatusChange) return;
    const unavailable =
      !!catalog.data &&
      (!catalog.data.enabled || !catalog.data.reachable || !!catalog.data.stale);
    onKllmStatusChange(unavailable);
  }, [catalog.data, onKllmStatusChange]);

  const messages = useMemo<ChatMessage[]>(
    () =>
      activeId && Object.prototype.hasOwnProperty.call(localMessages, activeId)
        ? localMessages[activeId]
        : conversation.data?.id === activeId
          ? conversation.data.messages.map(toChatMessage)
          : [],
    [activeId, conversation.data, localMessages],
  );
  const error = errors[activeId ?? 'new'] ?? null;
  const lastMessageContent = messages[messages.length - 1]?.content;
  const busy = !!busyChats[activeId ?? 'new'];
  const modelStatus = catalog.data;
  const storedModel = activeId
    ? modelByConversation[activeId] ?? conversations.data?.find((item) => item.id === activeId)?.model ?? conversation.data?.model ?? ''
    : modelByConversation.new ?? '';
  const visibleModels = useMemo(() => visibleChatModels(modelStatus), [modelStatus]);
  const selectedModel = useMemo(() => {
    if (storedModel && visibleModels.some((item) => item.key === storedModel)) return storedModel;
    return visibleModels.find((item) => isModelSelectable(item))?.key ?? visibleModels[0]?.key ?? '';
  }, [storedModel, visibleModels]);
  const selectedModelIdentity = visibleModels.find((item) => item.key === selectedModel) ?? null;
  const selectedModelReady = visibleModels.some(
    (item) => item.key === selectedModel && isModelSelectable(item),
  );

  // The meter is derived only from the selected conversation: local streaming
  // state is keyed by conversation id, and the fetched detail is used only when
  // its id matches the active one. The composer draft is the next prompt, so it
  // participates in the "next request" estimate exactly as in Temporary Chat.
  const contextChat = useMemo<TemporaryChat | null>(() => {
    const base: TemporaryChat = {
      id: activeId ?? 'persistent-new-conversation',
      title: activeId ?? 'New chat',
      model: selectedModel || null,
      messages,
      createdAt: 0,
      updatedAt: 0,
    };
    return withPendingChatDraft(base, draft);
  }, [activeId, draft, messages, selectedModel]);

  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const message = messages[i];
      if (message.role === 'assistant' && message.status !== 'streaming') return message.id;
    }
    return null;
  }, [messages]);

  const contextInfo = useMemo(
    () =>
      nextRequestContextMeter(contextChat, selectedModelIdentity?.context_window ?? null, {
        // The streaming answer's live usage belongs to this request, so only a
        // finished answer is shown as secondary "last response" usage.
        historicalTokens: lastAssistantId ? metrics[lastAssistantId]?.contextUsed ?? null : null,
        // The persistent backend fits stored turns without sending the
        // in-memory incomplete markers the temporary frontend path appends.
        includeIncompleteMarkers: false,
      }),
    [contextChat, selectedModelIdentity?.context_window, lastAssistantId, metrics],
  );

  const speechEnabled = isActive && enabled && !speechStatus.isError && speechStatus.data?.enabled === true;
  const speechChatKey = activeId ?? 'persistent-new-conversation';
  const handleSpeechTranscript = useCallback((text: string, chatId: string): string | null => {
    if (chatId !== (activeId ?? 'persistent-new-conversation')) return formatSpeechError('speech_unavailable');
    const result = insertTranscript(draft, text, CHAT_MAX_MESSAGE_CHARS);
    if (!result.ok) return formatSpeechError(result.reason === 'empty' ? 'no_speech' : 'message_too_long');
    setDraft(result.value, chatId);
    if (chatId === (activeId ?? 'persistent-new-conversation')) setSpeechTranscript(result.value);
    setErrors((current) => { const next = { ...current }; delete next[chatId]; return next; });
    setSpeechInsertToken((token) => token + 1);
    return null;
  }, [activeId, draft, setDraft]);
  const speech = useSpeechToText({
    enabled: speechEnabled,
    disabled: !isActive || !enabled || busy || !selectedModelReady,
    chatId: speechChatKey,
    maxRecordingSeconds: speechStatus.data?.max_recording_seconds ?? 60,
    readiness: speechStatus.data?.state ?? 'unavailable',
    onTranscript: handleSpeechTranscript,
  });

  const handleRename = async (id: string) => {
    const title = renameTitle.trim();
    if (!title) return;
    try {
      await api.renamePersistentChat(id, title);
      await queryClient.invalidateQueries({ queryKey: ['persistent-chat', 'conversations'] });
      setRenamingId(null);
      setRenameTitle('');
    } catch (cause) {
      toast({ title: 'Could not rename conversation', description: cause instanceof Error ? cause.message : undefined, type: 'error' });
    }
  };

  const invalidate = (chatId: string) => {
    void queryClient.invalidateQueries({ queryKey: ['persistent-chat', 'conversation', chatId] });
    void queryClient.invalidateQueries({ queryKey: ['persistent-chat', 'conversations'] });
  };

  const runStream = async (
    chatId: string,
    path: string,
    body: unknown,
    method: 'POST' | 'PUT',
    userContent?: string,
    baseMessagesOverride?: ChatMessage[],
  ) => {
    const controller = new AbortController();
    const assistantId = `pending-${crypto.randomUUID()}`;
    controllersRef.current.set(chatId, controller);
    setBusyChats((current) => ({ ...current, [chatId]: true }));
    setErrors((current) => { const next = { ...current }; delete next[chatId]; return next; });
    const startedAt = Date.now();
    setActivityByChat((current) => ({
      ...current,
      [chatId]: {
        assistantMessageId: assistantId,
        startedAt,
        status: null,
        hasPrefillProgress: false,
        hasContent: false,
      },
    }));
    setMetrics((current) => ({ ...current, [assistantId]: { phase: 'preparing', startedAt: performance.now() } }));
    setEditingMessageId(null);
    const timestamp = currentTime();
    const userMessageId = userContent ? `user-${crypto.randomUUID()}` : null;
    const baseMessages = baseMessagesOverride ?? (localMessages[chatId]
      ?? (conversation.data?.id === chatId ? conversation.data.messages.map(toChatMessage) : []));
    setLocalMessages((current) => ({
      ...current,
      [chatId]: [
        ...baseMessages,
        ...(userContent && userMessageId ? [{ id: userMessageId, role: 'user' as const, content: userContent, status: 'complete' as const, createdAt: timestamp }] : []),
        { id: assistantId, role: 'assistant', content: '', status: 'streaming', createdAt: timestamp, ...turnProvenance(selectedModel || null, selectedModelIdentity) },
      ],
    }));
    let finishReason: string | null | undefined;
    let streamError: Error | null = null;
    let receivedDelta = false;
    try {
      await streamPersistentTurn(path, body, {
        onDelta: (content) => {
          receivedDelta = true;
          setActivityByChat((current) => {
            const activity = current[chatId];
            if (activity?.assistantMessageId !== assistantId) return current;
            return { ...current, [chatId]: { ...activity, hasContent: true } };
          });
          setLocalMessages((current) => ({
            ...current,
            [chatId]: (current[chatId] ?? []).map((item) => item.id === assistantId ? { ...item, content: item.content + content } : item),
          }));
          setMetrics((current) => ({ ...current, [assistantId]: { ...current[assistantId], phase: 'generating' } }));
        },
        onDone: (reason) => {
          finishReason = reason;
          setMetrics((current) => ({ ...current, [assistantId]: { ...current[assistantId], phase: reason === 'length' ? 'truncated' : 'complete', endedAt: performance.now() } }));
        },
        onError: (streamErrorValue) => { streamError = streamErrorValue; },
        onStatus: (event) => {
          if (!receivedDelta) {
            if (event?.status) {
              setActivityByChat((current) => {
                const activity = current[chatId];
                if (activity?.assistantMessageId !== assistantId) return current;
                return {
                  ...current,
                  [chatId]: { ...activity, status: mergeBackendStatus(activity.status, event.status, event.phase) },
                };
              });
            }
            setMetrics((current) => ({ ...current, [assistantId]: { ...current[assistantId], phase: 'thinking' } }));
          }
        },
        onProgress: (event) => {
          if (receivedDelta || event.cache === undefined || event.processed === undefined || event.total === undefined) return;
          setActivityByChat((current) => {
            const activity = current[chatId];
            if (activity?.assistantMessageId !== assistantId) return current;
            return { ...current, [chatId]: { ...activity, hasPrefillProgress: true } };
          });
          const progress = { cache: event.cache, processed: event.processed, total: event.total };
          setMetrics((current) => ({ ...current, [assistantId]: { ...current[assistantId], phase: 'preparing', progress } }));
        },
        onUsage: (event) => setMetrics((current) => ({ ...current, [assistantId]: {
          ...current[assistantId],
          ...(event.completion_tokens !== undefined ? { outputTokens: event.completion_tokens } : {}),
          ...(event.prompt_tokens !== undefined ? { promptTokens: event.prompt_tokens } : {}),
          ...(event.cached_tokens !== undefined ? { cachedTokens: event.cached_tokens } : event.cache_read_input_tokens !== undefined ? { cachedTokens: event.cache_read_input_tokens } : {}),
        } })),
        onTimings: (event) => setMetrics((current) => ({ ...current, [assistantId]: {
          ...current[assistantId],
          ...(event.gen_n !== undefined ? { outputTokens: event.gen_n } : {}),
          ...(event.gen_ms !== undefined ? { genMs: event.gen_ms } : {}),
          ...(event.prompt_n !== undefined ? { promptTokens: event.prompt_n } : {}),
          ...(event.prompt_ms !== undefined ? { promptMs: event.prompt_ms } : {}),
          ...(event.cache_n !== undefined ? { cachedTokens: event.cache_n } : {}),
          ...(event.gen_tps !== undefined ? { genTps: event.gen_tps } : {}),
          ...(() => {
            const used = computeContextUsed({
              prompt_n: event.prompt_n,
              cache_n: event.cache_n,
              gen_n: event.gen_n,
            });
            return used === null ? {} : { contextUsed: used };
          })(),
        } })),
        onModel: (event) => {
          // The requested key stays on the turn; the provider's own id is
          // attribution only, never a rewrite of what the user selected.
          if (event.name) setLocalMessages((current) => ({
            ...current,
            [chatId]: (current[chatId] ?? []).map((item) => item.id === assistantId ? { ...item, upstreamModel: event.name } : item),
          }));
        },
      }, controller.signal, method);
      if (streamError) throw streamError;
      if (!finishReason || finishReason === 'incomplete') throw new Error('The response ended before completion.');
      await queryClient.invalidateQueries({ queryKey: ['persistent-chat', 'conversation', chatId] });
      await queryClient.invalidateQueries({ queryKey: ['persistent-chat', 'conversations'] });
      setLocalMessages((current) => { const next = { ...current }; delete next[chatId]; return next; });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Could not complete the response.';
      setErrors((current) => ({ ...current, [chatId]: message }));
      setMetrics((current) => ({ ...current, [assistantId]: { ...current[assistantId], phase: controller.signal.aborted ? 'stopped' : 'error', endedAt: performance.now() } }));
      setLocalMessages((current) => { const next = { ...current }; delete next[chatId]; return next; });
      invalidate(chatId);
      if (!controller.signal.aborted) toast({ title: 'Persistent Chat failed', description: message, type: 'error' });
    } finally {
      setActivityByChat((current) => {
        if (current[chatId]?.assistantMessageId !== assistantId) return current;
        const next = { ...current };
        delete next[chatId];
        return next;
      });
      if (controllersRef.current.get(chatId) === controller) controllersRef.current.delete(chatId);
      setBusyChats((current) => { const next = { ...current }; delete next[chatId]; return next; });
    }
  };

  const send = async () => {
    setSpeechTranscript(null);
    const content = draft.trim();
    if (!content || !enabled || busy || !selectedModelReady) return;
    speech.cancel();
    setDraft('');
    let conversationId = activeId;
    if (!conversationId) setBusyChats((current) => ({ ...current, new: true }));
    try {
      if (!conversationId) {
        const created = await api.createPersistentChat({ title: content.slice(0, 80), model: selectedModel });
        conversationId = created.id;
        setBusyChats((current) => ({ ...current, [created.id]: true }));
        setActiveId(created.id);
        setModelByConversation((current) => ({ ...current, [created.id]: selectedModel }));
        setLocalMessages((current) => ({ ...current, [created.id]: [] }));
        await queryClient.invalidateQueries({ queryKey: ['persistent-chat', 'conversations'] });
      }
      const path = `/conversations/${conversationId}/messages`;
      // The first-created conversation's detail query can settle after the stream begins.
      await runStream(conversationId, path, { content, model: selectedModel, reasoning_effort: reasoningEffort }, 'POST', content);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Could not create a conversation.';
      setErrors((current) => ({ ...current, [conversationId ?? 'new']: message }));
      setDraft(content, activeId ?? 'new');
      toast({ title: 'Could not start Persistent Chat', description: message, type: 'error' });
    } finally {
      if (!activeId) setBusyChats((current) => { const next = { ...current }; delete next.new; return next; });
    }
  };

  const remove = async (id: string) => {
    try {
      await api.deletePersistentChat(id);
      if (activeId === id) {
        controllersRef.current.get(id)?.abort();
        setActiveId(null);
        setLocalMessages((current) => { const next = { ...current }; delete next[id]; return next; });
      }
      invalidate(id);
    } catch (cause) {
      toast({ title: 'Could not delete conversation', description: cause instanceof Error ? cause.message : undefined, type: 'error' });
    }
  };

  const applyReplacement = async () => {
    if (!confirm || !activeId) return;
    const chatId = activeId;
    const { message, kind, content } = confirm;
    setConfirm(null);
    const chatMessages = localMessages[chatId] ?? conversation.data?.messages.map(toChatMessage) ?? [];
    const index = chatMessages.findIndex((item) => item.id === message.id);
    const userIndex = kind === 'edit' ? index : index - 1;
    const retained = chatMessages.slice(0, userIndex);
    const replacement = kind === 'edit' ? content : chatMessages[userIndex]?.content;
    if (!replacement) return;
    setLocalMessages((current) => ({ ...current, [chatId]: retained }));
    if (kind === 'edit') {
      await runStream(chatId, `/conversations/${chatId}/messages/${message.id}`, { content, model: selectedModel }, 'PUT', replacement, retained);
    } else {
      await runStream(chatId, `/conversations/${chatId}/messages/${message.id}/regenerate`, { model: selectedModel }, 'POST', replacement, retained);
    }
  };

  const activeTitle = conversations.data?.find((item) => item.id === activeId)?.title ?? 'Persistent Chat';

  const activeAssistantId = busy ? messages[messages.length - 1]?.id ?? null : null;
  const isThinking = !!busy && !lastMessageContent;
  const activityKey = activeId ?? 'new';
  const activeActivity = activityByChat[activityKey];
  useEffect(() => {
    const startedAt = activeActivity?.assistantMessageId === activeAssistantId ? activeActivity.startedAt : null;
    if (!busy || !activeAssistantId || !isThinking || startedAt === null) return;
    const timer = window.setInterval(() => setActivityClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [activeActivity?.startedAt, activeActivity?.assistantMessageId, activeAssistantId, busy, isThinking]);
  const elapsedSeconds = activeActivity?.assistantMessageId === activeAssistantId
    ? Math.max(0, Math.floor((activityClock - activeActivity.startedAt) / 1000))
    : 0;
  const activePhase = activeAssistantId ? metrics[activeAssistantId]?.phase : undefined;
  const generationPhase: 'preparing' | 'thinking' | 'generating' | null = !busy
    ? null
    : activePhase === 'generating'
      ? 'generating'
      : activePhase === 'thinking' || activePhase === 'preparing'
        ? 'thinking'
        : 'preparing';

  // The shared activity mapper is used by Temporary and Persistent Chat.
  // It only describes verified statuses/progress and hides once content starts.
  const activityLabel = busy
    ? activityLabelFor({
        status: activeActivity?.assistantMessageId === activeAssistantId ? activeActivity.status : null,
        hasPrefillProgress: activeActivity?.assistantMessageId === activeAssistantId && activeActivity.hasPrefillProgress,
        phase: activePhase ?? null,
        elapsedSeconds,
        hasContent: Boolean(lastMessageContent) || Boolean(activeActivity?.assistantMessageId === activeAssistantId && activeActivity.hasContent),
      })
    : null;

  useEffect(() => {
    const element = messageListRef.current;
    if (!element || !stickToBottomRef.current) return;
    element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' });
  }, [messages.length, lastMessageContent]);

  useEffect(() => {
    if (!isThinking || !thinkingOrbRef.current || !messageListRef.current) return;
    const element = messageListRef.current;
    const orb = thinkingOrbRef.current;
    element.scrollTo({ top: Math.max(0, orb.offsetTop - element.clientHeight / 2 + orb.clientHeight / 2), behavior: 'smooth' });
  }, [isThinking]);

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden">
      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-transparent">
        <ChatTopBar
          title={(
            <div className="flex min-w-0 items-center gap-1.5">
              {renamingId === activeId && activeId ? (
                <form className="flex min-w-0 items-center gap-1" onSubmit={(event) => { event.preventDefault(); void handleRename(activeId); }}>
                  <input
                    aria-label="Conversation name"
                    autoFocus
                    maxLength={200}
                    value={renameTitle}
                    onChange={(event) => setRenameTitle(event.target.value)}
                    className="h-8 min-w-0 w-48 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                  <button type="submit" className="inline-grid h-8 w-8 place-items-center rounded-md hover:bg-muted" aria-label="Save conversation name"><Check size={15} /></button>
                  <button type="button" onClick={() => setRenamingId(null)} className="inline-grid h-8 w-8 place-items-center rounded-md hover:bg-muted" aria-label="Cancel rename"><X size={15} /></button>
                </form>
              ) : (
                <h1 className="truncate text-[15px] font-semibold tracking-tight text-foreground">{activeTitle}</h1>
              )}
              {activeId && renamingId !== activeId ? (
                <button
                  type="button"
                  onClick={() => { setRenameTitle(activeTitle); setRenamingId(activeId); }}
                  disabled={!enabled}
                  className="chat-ink inline-grid h-7 w-7 shrink-0 place-items-center rounded-md transition hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label="Rename conversation"
                  title={enabled ? 'Rename conversation' : 'Persistent Chat is read-only'}
                ><Pencil size={13} /></button>
              ) : null}
            </div>
          )}
          activeMode={activeMode}
          temporaryEnabled={temporaryEnabled}
          persistentEnabled={persistentEnabled}
          onModeChange={onModeChange}
          model={selectedModelIdentity}
          contextInfo={contextInfo}
          contextOpen={contextOpen}
          onContextOpenChange={(open) => setOpenMenu(open ? 'context' : null)}
          onRefreshModels={() => { void catalog.refetch(); }}
          sessionSlot={(
            <PersistentChatTabs
              items={(conversations.data ?? []).map((item, index) => ({
                id: item.id,
                title: item.title?.trim() || `Conversation ${index + 1}`,
              }))}
              activeId={activeId}
              canCreate={enabled}
              onSelect={(id) => { setActiveId(id); setEditingMessageId(null); setRenamingId(null); setConfirm(null); }}
              onDelete={(id) => { void remove(id); }}
              onNew={() => { setActiveId(null); setEditingMessageId(null); setRenamingId(null); setConfirm(null); }}
            />
          )}
        />

        <nav aria-label="Persistent conversations" className="hidden w-full shrink-0 border-b border-border/60 bg-background/85 backdrop-blur-md md:block">
          <div className="flex w-full items-center gap-1.5 px-3 py-1.5 md:px-6">
            <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:thin]">
              {(conversations.data ?? []).map((item, index) => {
                const active = activeId === item.id;
                const title = item.title?.trim() || `Conversation ${index + 1}`;
                return (
                  <div key={item.id} className={`group relative flex shrink-0 items-center rounded-md transition-colors ${active ? 'bg-muted/70 text-foreground' : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'}`}>
                    <button
                      type="button"
                      onClick={() => { setActiveId(item.id); setEditingMessageId(null); setRenamingId(null); setConfirm(null); }}
                      aria-current={active ? 'page' : undefined}
                      className="max-w-[170px] truncate px-3 py-2 pr-8 text-left text-[13px] font-medium md:max-w-[220px]"
                      title={title}
                    >
                      {title}
                    </button>
                    <button
                      type="button"
                      onClick={() => void remove(item.id)}
                      className={`absolute right-1 inline-flex h-6 w-6 items-center justify-center rounded-md transition hover:bg-error/10 hover:text-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 ${active ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'}`}
                      aria-label={`Delete ${title}`}
                      title="Delete conversation"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                );
              })}
            </div>
            <button
              type="button"
              onClick={() => { setActiveId(null); setEditingMessageId(null); setRenamingId(null); setConfirm(null); }}
              disabled={!enabled}
              className="chat-ink ml-auto inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs transition hover:bg-muted/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="New persistent chat"
              title={enabled ? 'New persistent chat' : 'Persistent Chat is read-only'}
            >
              <Plus size={15} />
              <span className="hidden sm:inline">New chat</span>
            </button>
          </div>
        </nav>

        <div
          ref={messageListRef}
          onScroll={(event) => {
            const element = event.currentTarget;
            stickToBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 96;
          }}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-transparent px-4 py-4 md:px-6 md:py-6"
        >
          {conversations.isLoading && <p className="mx-auto max-w-3xl py-2 text-xs text-muted-foreground">Loading saved conversations…</p>}
          {!activeId && messages.length === 0 ? (
            <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center text-center">
              <div className="flex w-full max-w-md flex-col items-center px-4">
                <span className="mb-5 inline-grid h-14 w-14 place-items-center rounded-2xl border border-brand/20 bg-brand/10 text-brand"><MessageCircle size={24} /></span>
                <h2 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">A chat that remembers</h2>
                <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">
                  Persistent Chat saves conversations to your account. Start a new chat by sending a message.
                </p>
              </div>
            </div>
          ) : (
            <ChatMessageList
              messages={messages}
              metrics={metrics}
              activeStreamMessageId={activeAssistantId}
              thinking={isThinking}
              activityLabel={activityLabel}
              thinkingOrbRef={thinkingOrbRef}
              canEdit={enabled && !busy}
              canRegenerate={enabled && !busy}
              editingMessageId={editingMessageId}
              onRetry={(messageId) => {
                const target = messages.find((item) => item.id === messageId);
                if (target) setConfirm({ message: target, kind: 'regenerate' });
              }}
              onRegenerate={(message) => setConfirm({ message, kind: 'regenerate' })}
              onBeginEdit={(id) => setEditingMessageId(id)}
              onCancelEdit={() => setEditingMessageId(null)}
              onEdit={(id, content) => {
                const target = messages.find((item) => item.id === id);
                if (target) setConfirm({ message: target, kind: 'edit', content });
              }}
            />
          )}
          {conversation.isError && <p className="mx-auto mt-5 max-w-3xl rounded-xl border border-error/30 bg-error/5 p-3 text-sm text-error">Could not load this conversation. It may have been deleted or access changed.</p>}
          {!enabled && <p className="mx-auto mt-5 max-w-3xl rounded-xl border border-warning/30 bg-warning/5 p-3 text-sm text-warning">Persistent Chat is disabled for new messages. Existing conversations remain available to read and delete.</p>}
          {error && <p className="mx-auto mt-3 max-w-3xl text-sm text-error" role="alert">{error}</p>}
        </div>
        <ChatComposer
          value={speechTranscript ?? draft}
          disabled={!enabled || busy || !selectedModelReady}
          sending={busy}
          canStop={busy}
          helperText={!enabled ? 'Persistent Chat is currently disabled.' : error}
          modelStatus={modelStatus}
          modelValue={selectedModel || null}
          reasoningEffort={reasoningEffort}
          onReasoningEffortChange={setReasoningEffort}
          onModelChange={(value) => setModelByConversation((current) => ({ ...current, [activeId ?? 'new']: value }))}
          onChange={(value) => {
            setDraft(value);
            setSpeechTranscript(null);
            if (error) setErrors((current) => { const next = { ...current }; delete next[activeId ?? 'new']; return next; });
          }}
          onSend={() => void send()}
          onStop={() => activeId && controllersRef.current.get(activeId)?.abort()}
          generationPhase={generationPhase}
          openMenu={openMenu}
          onOpenMenuChange={setOpenMenu}
          caretRequest={speechInsertToken}
          speech={speechEnabled ? {
            enabled: true,
            phase: speech.phase,
            error: speech.error,
            readiness: speechStatus.data?.state ?? 'unavailable',
            elapsedMs: speech.elapsedMs,
            maxSeconds: speech.maxSeconds,
            onStart: speech.start,
            onStop: speech.stop,
            onCancel: speech.cancel,
          } : undefined}
        />
      </section>
      <ConfirmDialog
        open={!!confirm}
        title={confirm?.kind === 'edit' ? 'Replace this turn?' : 'Regenerate this response?'}
        description="Later messages will be replaced. Your previous stored history is recoverable if generation fails."
        confirmLabel={confirm?.kind === 'edit' ? 'Save & Send' : 'Regenerate'}
        busy={busy}
        onCancel={() => setConfirm(null)}
        onConfirm={() => void applyReplacement()}
      />
    </div>
  );
}
