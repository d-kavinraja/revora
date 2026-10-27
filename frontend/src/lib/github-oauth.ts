import { api } from '@/lib/api';

/**
 * Shared GitHub OAuth start helper (same-origin BFF).
 *
 * Mints a fresh single-use `oauth_state` via `/api/auth/start` (so a stale
 * cookie from a previous/failed attempt is overwritten) and redirects the
 * browser to GitHub's authorize URL. `switchAccount` appends
 * `prompt=select_account` to force GitHub's account picker — the supported
 * way to let a user pick a different GitHub identity (re-opening the same
 * URL otherwise silently re-authenticates the current session).
 */
export interface StartGitHubOAuthOptions {
  switchAccount?: boolean;
}

export async function startGitHubOAuth(
  options: StartGitHubOAuthOptions = {}
): Promise<void> {
  const { switchAccount = false } = options;

  const config = await api.getAuthConfig();
  const clientId = config.github_client_id;
  if (!clientId) {
    throw new Error('GitHub Client ID is not configured on the backend.');
  }

  const startRes = await fetch('/api/auth/start', { cache: 'no-store' });
  if (!startRes.ok) {
    throw new Error('Could not start the GitHub sign-in flow.');
  }
  const { state } = (await startRes.json()) as { state: string };

  const redirectUri = `${window.location.origin}/auth/callback`;
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    scope: 'read:user,user:email',
    state,
  });
  if (switchAccount) {
    params.set('prompt', 'select_account');
  }
  window.location.href = `https://github.com/login/oauth/authorize?${params.toString()}`;
}