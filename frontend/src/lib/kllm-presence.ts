/**
 * Browser-side helpers for advisory kLLM presence.
 *
 * The identifier is per browser tab (sessionStorage), not a credential. It
 * only scopes a heartbeat so Revora can tell whether somebody is actively
 * using the application before requesting an automatic model load.
 */

export const KLLM_SESSION_STORAGE_KEY = 'revora.kllm.tab-session';
export const KLLM_ACTIVE_WINDOW_MS = 120_000;
export const KLLM_HEARTBEAT_INTERVAL_MS = 30_000;

const USE_API_PROXY = process.env.NEXT_PUBLIC_USE_API_PROXY === 'true';
const PRESENCE_ENDPOINT = (
  USE_API_PROXY ? '/api/v1' : process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1'
) + '/kllm/session/end';

export function generateBrowserSessionId(): string {
  if (typeof crypto === 'undefined' || typeof crypto.getRandomValues !== 'function') {
    throw new Error('Secure browser randomness is unavailable');
  }
  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Return the current tab's stable presence id, creating it on first use. */
export function getBrowserSessionId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const existing = window.sessionStorage.getItem(KLLM_SESSION_STORAGE_KEY);
    if (existing) return existing;
    const generated = generateBrowserSessionId();
    window.sessionStorage.setItem(KLLM_SESSION_STORAGE_KEY, generated);
    return generated;
  } catch {
    // Private-mode/storage denial: fall back to a per-page id. Stale rows
    // expire server-side, so this never leaves a session active forever.
    return generateBrowserSessionId();
  }
}

export function isRecentlyInteractive(
  lastInteractionAt: number,
  now: number = Date.now(),
  windowMs: number = KLLM_ACTIVE_WINDOW_MS,
): boolean {
  return Number.isFinite(lastInteractionAt) && now - lastInteractionAt <= windowMs;
}

export function isPresenceActivityEvent(type: string): boolean {
  return (
    type === 'pointerdown' ||
    type === 'keydown' ||
    type === 'wheel' ||
    type === 'touchstart' ||
    type === 'focus'
  );
}

/** Best-effort end signal. Never throws and never blocks navigation. */
export async function endBrowserPresence(
  clientSessionId: string | null,
  token: string | null = null,
): Promise<void> {
  if (!clientSessionId || typeof window === 'undefined') return;
  try {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    await fetch(PRESENCE_ENDPOINT, {
      method: 'POST',
      credentials: 'include',
      keepalive: true,
      headers,
      body: JSON.stringify({ client_session_id: clientSessionId, active: false }),
    });
  } catch {
    // Presence is advisory; a missed end signal is covered by the TTL.
  }
}
