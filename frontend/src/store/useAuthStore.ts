import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  image?: string;
  /** GitHub login handle from OAuth (non-secret identity field). */
  github_username?: string;
}

/**
 * Raw profile shape any auth API may return. The login payloads
 * (POST /auth/login, POST /auth/github) use `image`; GET /auth/me
 * serializes the DB field name `avatar_url`. Both are accepted here.
 */
export interface RawUserProfile {
  id: string;
  email: string;
  name: string;
  role: string;
  image?: string | null;
  avatar_url?: string | null;
  github_username?: string | null;
}

/**
 * Accept only avatar URLs that are safe to render in an <img> tag:
 * absolute https URLs (e.g. avatars.githubusercontent.com) or
 * same-origin-relative paths. Rejects http:, protocol-relative (//),
 * data:, blob:, javascript: and malformed values. Returns undefined
 * when no candidate is usable, so callers fall back to the initial.
 */
export function pickAvatarUrl(
  ...candidates: Array<string | null | undefined>
): string | undefined {
  for (const c of candidates) {
    if (typeof c !== 'string') continue;
    const v = c.trim();
    if (!v) continue;
    if (v.startsWith('https://')) return v;
    if (v.startsWith('/') && !v.startsWith('//')) return v;
  }
  return undefined;
}

/**
 * Single normalization point for every user object entering the store.
 * Login payloads carry `image`; /auth/me carries `avatar_url`.
 * Normalizing here (instead of in each component) keeps the store the
 * single source of truth, so a page refresh can never silently drop
 * the avatar — the bug where /auth/me overwrote `image` with nothing.
 */
export function normalizeUserProfile(raw: RawUserProfile): User {
  return {
    id: raw.id,
    email: raw.email,
    name: raw.name,
    role: raw.role,
    image: pickAvatarUrl(raw.avatar_url, raw.image),
    github_username: raw.github_username ?? undefined,
  };
}

interface AuthState {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  /** True once the initial /auth/me restore attempt has settled (success or
   *  failure). Guards must wait for this before redirecting, otherwise a
   *  valid refresh would bounce to /login during the async restore. */
  sessionChecked: boolean;
  setAuth: (token: string, user: User) => void;
  markSessionChecked: () => void;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      isAuthenticated: false,
      sessionChecked: false,
      setAuth: (token, user) =>
        set({ token, user: normalizeUserProfile(user), isAuthenticated: true }),
      markSessionChecked: () => set({ sessionChecked: true }),
      logout: async () => {
        // Server-side revocation (bumps token_version) + cookie deletion,
        // both routed through the same-origin BFF so the browser actually
        // processes the Set-Cookie (first-party, SameSite=Lax in dev).
        // Local state clears regardless of the network result.
        try {
          await fetch('/api/auth/logout', { method: 'POST' });
        } catch {
          // network errors must not block local sign-out
        }
        set({ token: null, user: null, isAuthenticated: false });
      },
    }),
    {
      name: 'revora-auth',
      // SECURITY: the JWT is NEVER persisted to localStorage (XSS-stealable).
      // Only the non-secret profile survives reloads; the live credential is
      // the backend-set HttpOnly cookie, restored via /auth/me below.
      // sessionChecked is intentionally NOT persisted — it is a per-load flag.
      partialize: (state) => ({ user: state.user }),
      // Force rehydration to the current shape: any token/isAuthenticated
      // values left in localStorage by OLDER builds are discarded, so a
      // stale JS-readable credential can never come back from the dead.
      merge: (persisted, current) => ({
        ...current,
        token: null,
        isAuthenticated: false,
        sessionChecked: false,
        user: (persisted as { user?: User | null } | null)?.user ?? null,
      }),
    }
  )
);
