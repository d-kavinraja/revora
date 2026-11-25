export type SpeechPhase =
  | 'idle'
  | 'requesting'
  | 'recording'
  | 'uploading'
  | 'queued'
  | 'processing'
  | 'done'
  | 'cancelled'
  | 'error';

export type SpeechStreamEvent =
  | { type: 'queued' }
  | { type: 'processing' }
  | { type: 'result'; text: string }
  | { type: 'error'; code: string; message: string };

export class SpeechRequestError extends Error {
  code: string;
  status?: number;

  constructor(message: string, code = 'speech_upstream_error', status?: number) {
    super(message);
    this.name = 'SpeechRequestError';
    this.code = code;
    this.status = status;
  }
}

const MAX_EVENT_CHARS = 64 * 1024;
const MAX_TRANSCRIPT_CHARS = 20_000;

function eventFromLine(line: string): SpeechStreamEvent | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  if (trimmed.length > MAX_EVENT_CHARS) {
    throw new SpeechRequestError('Speech returned an invalid response.', 'speech_upstream_error');
  }
  let value: unknown;
  try {
    value = JSON.parse(trimmed);
  } catch {
    throw new SpeechRequestError('Speech returned an invalid response.', 'speech_upstream_error');
  }
  if (!value || typeof value !== 'object') {
    throw new SpeechRequestError('Speech returned an invalid response.', 'speech_upstream_error');
  }
  const record = value as Record<string, unknown>;
  if (record.type === 'queued') return { type: 'queued' };
  if (record.type === 'processing') return { type: 'processing' };
  if (record.type === 'result') {
    const text = typeof record.text === 'string' ? record.text.trim() : '';
    if (!text || text.length > MAX_TRANSCRIPT_CHARS) {
      throw new SpeechRequestError('Speech returned an invalid result.', 'speech_upstream_error');
    }
    return { type: 'result', text };
  }
  if (record.type === 'error') {
    return {
      type: 'error',
      code: typeof record.code === 'string' ? record.code : 'speech_upstream_error',
      message:
        typeof record.message === 'string' && record.message
          ? record.message.slice(0, 300)
          : 'Speech could not be transcribed.',
    };
  }
  throw new SpeechRequestError('Speech returned an invalid response.', 'speech_upstream_error');
}

export class SpeechNdjsonParser {
  private buffer = '';

  push(chunk: string): SpeechStreamEvent[] {
    this.buffer += chunk;
    const events: SpeechStreamEvent[] = [];
    while (true) {
      const index = this.buffer.indexOf('\n');
      if (index < 0) break;
      const line = this.buffer.slice(0, index).replace(/\r$/, '');
      this.buffer = this.buffer.slice(index + 1);
      const event = eventFromLine(line);
      if (event) events.push(event);
    }
    if (this.buffer.length > MAX_EVENT_CHARS) {
      throw new SpeechRequestError('Speech returned an invalid response.', 'speech_upstream_error');
    }
    return events;
  }

  flush(): SpeechStreamEvent[] {
    if (!this.buffer.trim()) {
      this.buffer = '';
      return [];
    }
    const event = eventFromLine(this.buffer);
    this.buffer = '';
    return event ? [event] : [];
  }
}

export function insertTranscript(
  draft: string,
  transcript: string,
  maxChars: number,
):
  | { ok: true; value: string; caret: number }
  | { ok: false; reason: 'empty' | 'too_long' } {
  const text = transcript.replace(/\s+/g, ' ').trim();
  if (!text) return { ok: false, reason: 'empty' };
  const separator = draft.length === 0 || /\s$/.test(draft) ? '' : ' ';
  const value = `${draft}${separator}${text}`;
  if (value.length > maxChars) return { ok: false, reason: 'too_long' };
  return { ok: true, value, caret: value.length };
}

export function pickRecorderMime(
  isSupported: (mime: string) => boolean,
): string | null {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ];
  for (const mime of candidates) {
    if (isSupported(mime)) return mime;
  }
  return null;
}

export function formatSpeechError(code: string): string {
  switch (code) {
    case 'permission_denied':
      return 'Microphone access was denied. Allow microphone access in your browser and try again.';
    case 'microphone_unavailable':
      return 'No microphone was found. Check your device and try again.';
    case 'not_secure_context':
      return 'Voice input needs a secure HTTPS connection.';
    case 'unsupported_browser':
      return 'Voice input is not supported in this browser.';
    case 'recording_failed':
      return 'The recording could not be captured. Try again.';
    case 'empty_transcript':
      return 'No words were detected. Try again a little closer to the microphone.';
    case 'message_too_long':
      return 'The transcript would make this message too long. Shorten the draft and try again.';
    case 'no_speech':
      return 'No speech was detected. Try again.';
    case 'audio_too_large':
      return 'That recording is too large. Record a shorter message.';
    case 'audio_too_long':
      return 'That recording is too long. Record a shorter message.';
    case 'unsupported_audio_type':
    case 'invalid_audio':
      return 'That recording could not be read. Try again.';
    case 'speech_disabled':
      return 'Voice input is turned off by an administrator.';
    case 'speech_not_ready':
    case 'speech_unavailable':
      return 'Voice input is temporarily unavailable. Try again shortly.';
    case 'speech_queue_full':
    case 'speech_busy':
      return 'Voice input is busy right now. Try again in a moment.';
    case 'speech_rate_limited':
      return 'Too many voice requests. Wait a moment and try again.';
    case 'speech_timeout':
      return 'Voice input took too long. Try a shorter recording.';
    case 'unauthorized':
      return 'Your session has expired. Sign in again.';
    default:
      return 'Voice input failed. Try again.';
  }
}
export async function parseSpeechErrorResponse(response: Response): Promise<SpeechRequestError> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const root = (payload ?? {}) as Record<string, unknown>;
  const detail = (root.detail ?? {}) as Record<string, unknown> | string;
  const detailObject = typeof detail === 'object' && detail ? detail : {};
  const code =
    (typeof root.code === 'string' && root.code) ||
    (typeof detailObject.code === 'string' && detailObject.code) ||
    (response.status === 401 ? 'unauthorized' : 'speech_upstream_error');
  const message =
    (typeof root.message === 'string' && root.message) ||
    (typeof detail === 'string' && detail) ||
    (typeof detailObject.message === 'string' && detailObject.message) ||
    '';
  return new SpeechRequestError(message || formatSpeechError(code), code, response.status);
}

export async function readSpeechStream(
  response: Response,
  onEvent: (event: SpeechStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) {
    throw new SpeechRequestError('Speech returned no response.', 'speech_upstream_error');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SpeechNdjsonParser();
  let terminal = false;
  try {
    while (!terminal) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const { value, done } = await reader.read();
      if (done) break;
      const text = decoder.decode(value, { stream: true });
      for (const event of parser.push(text)) {
        onEvent(event);
        if (event.type === 'result' || event.type === 'error') {
          terminal = true;
          break;
        }
      }
    }
    if (!terminal) {
      const tail = decoder.decode();
      for (const event of parser.push(tail)) {
        onEvent(event);
        if (event.type === 'result' || event.type === 'error') {
          terminal = true;
          break;
        }
      }
    }
    if (!terminal) {
      for (const event of parser.flush()) {
        onEvent(event);
        if (event.type === 'result' || event.type === 'error') {
          terminal = true;
          break;
        }
      }
    }
    if (!terminal) {
      throw new SpeechRequestError('Speech returned no result.', 'speech_upstream_error');
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // The stream may already be closed; there is nothing to retain.
    }
  }
}

export type SpeechReadiness =
  | 'disabled'
  | 'ready'
  | 'unavailable'
  | 'recovering'
  | 'authentication_error'
  | 'configuration_error'
  | 'error';

export function isSpeechAvailabilityError(code: string): boolean {
  return (
    code === 'speech_unavailable' ||
    code === 'speech_not_ready' ||
    code === 'speech_upstream_error' ||
    code === 'speech_timeout'
  );
}

export function speechReadinessMessage(state: SpeechReadiness): string {
  switch (state) {
    case 'disabled':
      return 'Voice input is turned off by an administrator.';
    case 'unavailable':
      return 'Voice input is temporarily unavailable. Retrying automatically.';
    case 'recovering':
      return 'Voice input is recovering. Try again shortly.';
    case 'authentication_error':
      return 'Voice input could not authenticate. Contact an administrator.';
    case 'configuration_error':
      return 'Voice input is not configured.';
    case 'error':
      return 'Voice input is unavailable right now.';
    case 'ready':
    default:
      return '';
  }
}

export function shouldClearStaleSpeechError(
  phase: SpeechPhase,
  errorCode: string | null,
  readiness: SpeechReadiness,
): boolean {
  return (
    phase === 'error' &&
    errorCode !== null &&
    isSpeechAvailabilityError(errorCode) &&
    readiness === 'ready'
  );
}
