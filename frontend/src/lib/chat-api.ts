import { API_BASE } from '@/lib/api-transport';
import { useAuthStore } from '@/store/useAuthStore';
import {
  extractSseFrames,
  parseSseFrame,
  type ChatSseEvent,
} from '@/lib/chat-stream-parser';

export type ChatUsageEvent = Extract<ChatSseEvent, { type: 'usage' }>;
export type ChatTimingsEvent = Extract<ChatSseEvent, { type: 'timings' }>;
export type ChatStatusEvent = Extract<ChatSseEvent, { type: 'status' }>;
export type ChatProgressEvent = Extract<ChatSseEvent, { type: 'progress' }>;
export type ChatModelEvent = Extract<ChatSseEvent, { type: 'model' }>;

export interface ChatCompletionMessage {
  role: 'user' | 'assistant';
  content: string;
}

export type ReasoningEffort = 'low' | 'medium' | 'high' | 'max';

export interface ChatCompletionPayload {
  model: string;
  messages: ChatCompletionMessage[];
  stream?: boolean;
  max_tokens?: number;
  temperature?: number;
  reasoning_effort?: ReasoningEffort;
}

export class ChatRequestError extends Error {
  status?: number;
  code?: string;

  constructor(message: string, status?: number, code?: string) {
    super(message);
    this.name = 'ChatRequestError';
    this.status = status;
    this.code = code;
  }
}

export class ChatAuthError extends ChatRequestError {
  constructor(message = 'Your session has expired. Please sign in again.') {
    super(message, 401, 'unauthorized');
    this.name = 'ChatAuthError';
  }
}

function authHeaders(): HeadersInit {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function parseError(response: Response): Promise<ChatRequestError> {
  let detail: unknown = undefined;
  try {
    detail = await response.json();
  } catch {
    // ignore
  }
  const obj = detail as { detail?: unknown; message?: unknown; code?: unknown } | null;
  const detailObj = obj?.detail as { message?: unknown; code?: unknown } | string | undefined;
  const message =
    (typeof detailObj === 'string' && detailObj) ||
    (typeof (detailObj as { message?: unknown })?.message === 'string' &&
      ((detailObj as { message?: unknown }).message as string)) ||
    (typeof obj?.message === 'string' && obj.message) ||
    (response.status === 429
      ? "You're sending messages too quickly. Please wait a moment and try again."
      : response.status >= 500
        ? 'Chat is temporarily unavailable. Please try again.'
        : `Chat request failed (HTTP ${response.status}).`);
  const code =
    (typeof (detailObj as { code?: unknown })?.code === 'string' &&
      ((detailObj as { code?: unknown }).code as string)) ||
    (typeof obj?.code === 'string' ? obj.code : undefined);
  if (response.status === 401) return new ChatAuthError(message);
  return new ChatRequestError(message, response.status, code);
}

export async function streamChatCompletion(
  payload: ChatCompletionPayload,
  handlers: {
    onDelta: (content: string) => void;
    onDone: (finishReason?: string | null) => void;
    onError: (error: ChatRequestError) => void;
    onUsage?: (usage: ChatUsageEvent) => void;
    onTimings?: (timings: ChatTimingsEvent) => void;
    onStatus?: (status: ChatStatusEvent) => void;
    onProgress?: (progress: ChatProgressEvent) => void;
    onModel?: (model: ChatModelEvent) => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/chat/completions`, {
      method: 'POST',
      credentials: 'include',
      headers: authHeaders(),
      body: JSON.stringify({ ...payload, stream: true }),
      signal,
    });
  } catch (error) {
    if ((error as Error)?.name === 'AbortError') throw error;
    throw new ChatRequestError('Could not reach Revora. Check your connection and try again.');
  }

  if (!response.ok) {
    throw await parseError(response);
  }
  if (!response.body) {
    throw new ChatRequestError('Chat response did not include a stream.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const handleEvent = (event: ChatSseEvent) => {
    if (event.type === 'delta') handlers.onDelta(event.content);
    if (event.type === 'done') handlers.onDone(event.finish_reason);
    if (event.type === 'error') {
      handlers.onError(new ChatRequestError(event.message || 'Chat request failed.', undefined, event.code));
    }
    if (event.type === 'usage') handlers.onUsage?.(event);
    if (event.type === 'timings') handlers.onTimings?.(event);
    if (event.type === 'status') handlers.onStatus?.(event);
    if (event.type === 'progress') handlers.onProgress?.(event);
    if (event.type === 'model') handlers.onModel?.(event);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { frames, rest } = extractSseFrames(buffer);
    buffer = rest;
    for (const frame of frames) {
      const event = parseSseFrame(frame);
      if (event) handleEvent(event);
    }
  }

  const tail = decoder.decode();
  if (tail) buffer += tail;
  if (buffer.trim()) {
    const { frames } = extractSseFrames(`${buffer}\n\n`);
    for (const frame of frames) {
      const event = parseSseFrame(frame);
      if (event) handleEvent(event);
    }
  }
}
