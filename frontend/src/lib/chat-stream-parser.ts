export type ChatSseEvent =
  | { type: 'delta'; content: string }
  | { type: 'done'; finish_reason?: string | null }
  | { type: 'error'; code?: string; message?: string }
  | {
      type: 'usage';
      prompt_tokens?: number;
      completion_tokens?: number;
      total_tokens?: number;
      cache_read_input_tokens?: number;
      cached_tokens?: number;
    }
  | {
      type: 'timings';
      prompt_n?: number;
      prompt_ms?: number;
      prompt_tps?: number;
      gen_n?: number;
      gen_ms?: number;
      gen_tps?: number;
      cache_n?: number;
    }
  | {
      type: 'status';
      status: 'thinking' | 'waking' | 'queued';
      phase?: string;
      elapsed_seconds?: number;
    }
  | {
      type: 'progress';
      cache?: number;
      processed?: number;
      total?: number;
    }
  | { type: 'model'; name?: string };

export function extractSseFrames(buffer: string): { frames: string[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const parts = normalized.split('\n\n');
  const rest = parts.pop() ?? '';
  const frames = parts.map((p) => p.trim()).filter(Boolean);
  return { frames, rest };
}

function optionalNumber(
  obj: Record<string, unknown>,
  key: string,
): Record<string, number> {
  const value = obj[key];
  return typeof value === 'number' && Number.isFinite(value) ? { [key]: value } : {};
}

export function parseSseFrame(frame: string): ChatSseEvent | null {
  const dataLines = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart());
  if (dataLines.length === 0) return null;
  const data = dataLines.join('\n').trim();
  if (!data || data === '[DONE]') {
    return data === '[DONE]' ? { type: 'done', finish_reason: 'stop' } : null;
  }
  try {
    const parsed = JSON.parse(data) as Record<string, unknown>;
    if (parsed.type === 'delta' && typeof parsed.content === 'string') {
      return { type: 'delta', content: parsed.content };
    }
    if (parsed.type === 'done') {
      return {
        type: 'done',
        finish_reason:
          typeof parsed.finish_reason === 'string' ? parsed.finish_reason : null,
      };
    }
    if (parsed.type === 'error') {
      return {
        type: 'error',
        code: typeof parsed.code === 'string' ? parsed.code : undefined,
        message: typeof parsed.message === 'string' ? parsed.message : undefined,
      };
    }
    if (parsed.type === 'usage') {
      return {
        type: 'usage',
        ...optionalNumber(parsed, 'prompt_tokens'),
        ...optionalNumber(parsed, 'completion_tokens'),
        ...optionalNumber(parsed, 'total_tokens'),
        ...optionalNumber(parsed, 'cache_read_input_tokens'),
        ...optionalNumber(parsed, 'cached_tokens'),
      };
    }
    if (parsed.type === 'timings') {
      return {
        type: 'timings',
        ...optionalNumber(parsed, 'prompt_n'),
        ...optionalNumber(parsed, 'prompt_ms'),
        ...optionalNumber(parsed, 'prompt_tps'),
        ...optionalNumber(parsed, 'gen_n'),
        ...optionalNumber(parsed, 'gen_ms'),
        ...optionalNumber(parsed, 'gen_tps'),
        ...optionalNumber(parsed, 'cache_n'),
      };
    }
    // Only neutral statuses are exposed. Raw reasoning_content is never parsed
    // or forwarded to the UI.
    if (
      parsed.type === 'status' &&
      (parsed.status === 'thinking' || parsed.status === 'waking' || parsed.status === 'queued')
    ) {
      const out: { type: 'status'; status: 'thinking' | 'waking' | 'queued'; phase?: string; elapsed_seconds?: number } = {
        type: 'status',
        status: parsed.status,
      };
      if (typeof parsed.phase === 'string') out.phase = parsed.phase;
      if (typeof parsed.elapsed_seconds === 'number' && Number.isFinite(parsed.elapsed_seconds)) {
        out.elapsed_seconds = parsed.elapsed_seconds;
      }
      return out;
    }
    if (parsed.type === 'progress') {
      return {
        type: 'progress',
        ...optionalNumber(parsed, 'cache'),
        ...optionalNumber(parsed, 'processed'),
        ...optionalNumber(parsed, 'total'),
      };
    }
    if (parsed.type === 'model' && typeof parsed.name === 'string' && parsed.name.trim()) {
      return { type: 'model', name: parsed.name };
    }
  } catch {
    return null;
  }
  return null;
}
