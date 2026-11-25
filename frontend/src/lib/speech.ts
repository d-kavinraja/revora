import { API_BASE } from '@/lib/api-transport';
import { useAuthStore } from '@/store/useAuthStore';
import {
  SpeechRequestError,
  parseSpeechErrorResponse,
  readSpeechStream,
  type SpeechStreamEvent,
} from '@/lib/speech-core';

export * from '@/lib/speech-core';

function authHeaders(): HeadersInit {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = { Accept: 'application/x-ndjson' };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export async function transcribeAudio(
  audio: Blob,
  handlers: {
    onEvent: (event: SpeechStreamEvent) => void;
    signal?: AbortSignal;
  },
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/stt/transcribe`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        ...authHeaders(),
        'Content-Type': audio.type || 'audio/webm',
      },
      body: audio,
      signal: handlers.signal,
    });
  } catch (error) {
    if ((error as Error)?.name === 'AbortError') throw error;
    throw new SpeechRequestError(
      'Could not reach Revora. Check your connection and try again.',
      'speech_unavailable',
    );
  }
  if (!response.ok) throw await parseSpeechErrorResponse(response);
  await readSpeechStream(response, handlers.onEvent, handlers.signal);
}
