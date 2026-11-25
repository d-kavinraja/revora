import { API_BASE, type PersistentConversation, type PersistentConversationSummary } from '@/lib/api';
import { useAuthStore } from '@/store/useAuthStore';
import { extractSseFrames, parseSseFrame } from '@/lib/chat-stream-parser';
import type {
  ChatModelEvent,
  ChatProgressEvent,
  ChatRequestError,
  ChatStatusEvent,
  ChatTimingsEvent,
  ChatUsageEvent,
} from '@/lib/chat-api';

function headers(): HeadersInit {
  const token = useAuthStore.getState().token;
  return {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function responseError(response: Response): Promise<Error> {
  let body: { detail?: unknown } = {};
  try { body = await response.json(); } catch { /* no JSON error payload */ }
  const detail = body.detail;
  const message = typeof detail === 'string'
    ? detail
    : typeof detail === 'object' && detail && 'message' in detail
      ? String((detail as { message: unknown }).message)
      : `Persistent Chat request failed (HTTP ${response.status}).`;
  const error = new Error(message) as ChatRequestError;
  error.status = response.status;
  if (typeof detail === 'object' && detail && 'code' in detail) {
    error.code = String((detail as { code: unknown }).code);
  }
  return error;
}

export async function streamPersistentTurn(
  path: string,
  body: unknown,
  callbacks: {
    onDelta: (content: string) => void;
    onDone: (reason?: string | null) => void;
    onError: (error: Error) => void;
    onUsage?: (usage: ChatUsageEvent) => void;
    onTimings?: (timings: ChatTimingsEvent) => void;
    onStatus?: (status: ChatStatusEvent) => void;
    onProgress?: (progress: ChatProgressEvent) => void;
    onModel?: (model: ChatModelEvent) => void;
  },
  signal: AbortSignal,
  method: 'POST' | 'PUT' = 'POST',
): Promise<void> {
  const response = await fetch(`${API_BASE}/persistent-chat${path}`, {
    method,
    credentials: 'include',
    headers: headers(),
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw await responseError(response);
  if (!response.body) throw new Error('Persistent Chat response did not include a stream.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const process = (frame: string) => {
    const event = parseSseFrame(frame);
    if (!event) return;
    if (event.type === 'delta') callbacks.onDelta(event.content);
    if (event.type === 'done') callbacks.onDone(event.finish_reason);
    if (event.type === 'error') callbacks.onError(new Error(event.message || 'Generation failed.'));
    if (event.type === 'usage') callbacks.onUsage?.(event);
    if (event.type === 'timings') callbacks.onTimings?.(event);
    if (event.type === 'status') callbacks.onStatus?.(event);
    if (event.type === 'progress') callbacks.onProgress?.(event);
    if (event.type === 'model') callbacks.onModel?.(event);
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const extracted = extractSseFrames(buffer);
    buffer = extracted.rest;
    extracted.frames.forEach(process);
  }
  buffer += decoder.decode();
  if (buffer.trim()) extractSseFrames(`${buffer}\n\n`).frames.forEach(process);
}

export async function createPersistentConversation(
  body: { title?: string; model?: string | null },
): Promise<PersistentConversation> {
  const response = await fetch(`${API_BASE}/persistent-chat/conversations`, {
    method: 'POST', credentials: 'include', headers: headers(), body: JSON.stringify(body),
  });
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<PersistentConversation>;
}

export async function listPersistentConversations(): Promise<PersistentConversationSummary[]> {
  const response = await fetch(`${API_BASE}/persistent-chat/conversations`, {
    credentials: 'include', headers: headers(),
  });
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<PersistentConversationSummary[]>;
}
