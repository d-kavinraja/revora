import axios from 'axios';
import { useAuthStore, normalizeUserProfile } from '@/store/useAuthStore';

// Marks the session-restore request so the 401 interceptor skips it —
// restore failures belong to the dashboard guard (which routes
// `unauthorized` to /login and `unreachable` to the waking-up flow),
// never to the auto-logout path.
declare module 'axios' {
  interface AxiosRequestConfig {
    __revoraRestore?: boolean;
  }
}

// Same-origin proxy (P0-A): when NEXT_PUBLIC_USE_API_PROXY is 'true', every
// apiClient call, health ping, SSE stream, and media URL goes to /api/v1 on
// the frontend host — carrying the HttpOnly session cookie — and the Next
// rewrite (next.config.ts, BACKEND_ORIGIN-gated) forwards to Render.
// Disabled by default so local dev keeps its absolute localhost base,
// where the same-host cookie already flows without a proxy.
const USE_API_PROXY = process.env.NEXT_PUBLIC_USE_API_PROXY === 'true';
export const API_BASE = USE_API_PROXY
  ? '/api/v1'
  : process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';

export const apiClient = axios.create({
  baseURL: API_BASE,
  // Cookie-based session: the HttpOnly revora_auth_token cookie rides along
  // on every request (cross-origin). The Bearer header below is only the
  // in-memory token for the current tab — never persisted anywhere.
  withCredentials: true,
  headers: { 
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true'
  },
});

/** Ping the backend health endpoint. Returns true if server is alive, false if sleeping/unreachable. */
export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(12000) });
    return res.ok;
  } catch {
    return false;
  }
}

// Attach JWT token on every request (in-memory only; HttpOnly cookie is
// attached automatically via withCredentials for post-reload restores).
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * Restore the session after a full page reload. The JWT lives only in the
 * HttpOnly cookie (never localStorage), so the store starts with no token;
 * `/auth/me` proves the cookie is valid and repopulates the non-secret
 * profile. Safe to call at app start — resolves false when logged out.
 */
/**
 * Result of a session-restore attempt. `unauthorized` means the backend
 * rejected the credential (genuinely signed out / expired / revoked);
 * `unreachable` means no answer arrived at all (backend asleep, cold
 * start, timeout, network error) — never treat this as expiry.
 */
export type RestoreOutcome =
  | { ok: true }
  | { ok: false; reason: 'unauthorized' | 'unreachable' | 'disabled' };

// One bounded restore attempt with a cold-start-tolerant timeout (Render
// Free Tier regularly needs 30-60s to wake). Retry UX belongs to the
// waking-up page, not to a polling loop here.
const RESTORE_TIMEOUT_MS = 60_000;

export async function restoreSession(): Promise<RestoreOutcome> {
  try {
    const res = await apiClient.get<{
      id: string;
      email: string;
      name: string;
      role: string;
      image?: string;
      // GET /auth/me serializes the DB field name, not `image`.
      // normalizeUserProfile maps it so refresh keeps the avatar.
      avatar_url?: string | null;
      github_username?: string;
    }>('/auth/me', { timeout: RESTORE_TIMEOUT_MS, __revoraRestore: true });
    useAuthStore.setState({
      token: null, // never reintroduce a JS-readable token
      user: normalizeUserProfile(res.data),
      isAuthenticated: true,
      restoreReason: null,
    });
    return { ok: true };
  } catch (error) {
    const status = axios.isAxiosError(error) ? error.response?.status : undefined;
    const data = axios.isAxiosError(error) ? error.response?.data : undefined;
    const detail = String(data?.detail ?? '');
    const code = String(data?.code ?? '');
    let reason: 'unauthorized' | 'unreachable' | 'disabled';
    if (code === 'account_disabled' || detail.toLowerCase().includes('disabled') || status === 403) {
      reason = 'disabled';
    } else if (status === 401) {
      reason = 'unauthorized';
    } else {
      reason = 'unreachable';
    }
    useAuthStore.setState({ restoreReason: reason });
    return { ok: false, reason };
  } finally {
    // Unblock auth guards: the restore attempt has settled either way.
    useAuthStore.getState().markSessionChecked();
  }
}

/** Routes that require a session; mirrors proxy.ts AUTHENTICATED_ROUTE_PREFIXES. */
const PROTECTED_ROUTE_PREFIXES = [
  '/dashboard',
  '/settings',
  '/repositories',
  '/reviews',
  '/model-lab',
];

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

// Auto-logout on 401 — local-only by default: a failed request must never
// revoke a session that may still be valid server-side (e.g. the cookie
// never reached us, or the backend hiccupped). Server-side revocation
// happens solely on explicit user sign-out. Clears local state and, when
// on a protected route, hard-navigates to /login so a revoked/expired
// session can never strand the user on a screen stuck retrying requests.
apiClient.interceptors.response.use(
  (res) => res,
  (error) => {
    const status = error.response?.status;
    const data = error.response?.data;
    const detail = String(data?.detail ?? '');
    const code = String(data?.code ?? '');
    const isDisabled403 =
      status === 403 &&
      (code === 'account_disabled' || detail.toLowerCase().includes('disabled'));
    if (status === 401 || isDisabled403) {
      const url =
        typeof error.config?.url === 'string' ? error.config.url : '';
      const isRestore = !!error.config?.__revoraRestore;
      // Public endpoint: no session expected, nothing to clear.
      const isPublic = url.includes('/auth/config');
      // Admin console endpoints use their own isolated session/cookie and
      // self-guard at /admin/login. A 401 there (e.g. no admin cookie) must
      // never clear or redirect the *user* session.
      const isAdminEndpoint = url.includes('/admin/');
      const state = useAuthStore.getState();
      const onProtected =
        typeof window !== 'undefined' &&
        isProtectedPath(window.location.pathname);
      const loginTarget = isDisabled403 ? '/login?reason=disabled' : '/login';
      // Restore failures belong to the dashboard guard; public endpoints
      // and already-signed-out states need no logout round-trip. Logout
      // itself is single-flighted in the store, so concurrent 401s share
      // one clearing pass instead of stampeding.
      if (!isRestore && !isPublic && !isAdminEndpoint && state.isAuthenticated) {
        // Await the cookie-clearing logout BEFORE any hard navigation, so the
        // edge gate cannot bounce us straight back to the dashboard.
        void (async () => {
          await useAuthStore.getState().logout({ revoke: false });
          if (
            onProtected &&
            typeof window !== 'undefined' &&
            window.location.pathname !== '/login'
          ) {
            window.location.assign(loginTarget);
          }
        })();
      } else if (
        !state.isAuthenticated &&
        onProtected &&
        typeof window !== 'undefined' &&
        window.location.pathname !== '/login'
      ) {
        window.location.assign(loginTarget);
      }
    }
    return Promise.reject(error);
  }
);

export type ReviewStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'stopped' | 'timed_out' | 'waiting' | 'skipped' | 'queued';

export interface PullRequestInfo {
  id: string;
  pr_number: number;
  title: string;
  author: string;
  status: string;
  head_branch: string;
  base_branch: string;
  additions: number;
  deletions: number;
  changed_files: number;
}

export interface Review {
  id: string;
  status: ReviewStatus;
  summary: string | null;
  stats: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string | null;
  github_pr_state: string;
  pr_has_active_review: boolean;
  latest_review_id?: string | null;
  pull_request: PullRequestInfo;
  repository: { id?: string; name: string; full_name: string };
}

export interface ReviewExecution {
  id: string;
  execution_number: number;
  trigger: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  model: string | null;
  provider: string | null;
  tokens: Record<string, unknown>;
}

export interface Repository {
  id: string;
  name: string;
  full_name: string;
  description: string | null;
  language: string | null;
  is_private: boolean;
  is_archived: boolean;
  reviews_enabled: boolean;
  total_reviews: number;
  active_review_status?: 'queued' | 'pending' | 'running' | null;
  last_synced_at: string | null;
  last_reviewed_at: string | null;
  removed_at: string | null;
  permissions_ok: boolean;
  status?: 'active' | 'removed' | 'permission_required' | 'disabled';
  last_sync?: {
    completed_at: string | null;
    status: string | null;
    error: string | null;
    reason: string | null;
  } | null;
  // Durable per-repository sync state (backend source of truth — survives
  // browser refresh). "running" = sync in progress; "queued" = sync requested;
  // "stale" = orphaned run; "success"/"partial"/"failed" = terminal states.
  sync_state?: {
    status: string | null;
    reason: string | null;
    started_at: string | null;
    completed_at: string | null;
    error: string | null;
    prs_found?: number | null;
    prs_updated?: number | null;
    jobs_enqueued?: number | null;
  } | null;
  settings?: {
    assigned_provider?: string;
    assigned_model?: string;
    assigned_key_id?: string;
  };
}

export interface SyncRun {
  id: string;
  reason: 'startup' | 'background' | 'manual' | 'webhook' | 'recovery' | 'login' | string;
  status: 'running' | 'success' | 'partial' | 'failed' | 'queued' | 'stale' | string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  repo_count: number;
  repos_added: number;
  repos_updated: number;
  repos_removed: number;
  repos_failed: number;
  prs_found: number;
  prs_updated: number;
  jobs_enqueued: number;
  details: Record<string, string> | null;
}

export interface DashboardStats {
  connected_repos: number;
  total_prs_reviewed: number;
  total_issues_caught: number;
  total_completed_reviews: number;
  total_failed_reviews: number;
}

export interface ApiKey {
  id: string;
  provider: string;
  label: string;
  masked_key: string;
  is_valid: boolean;
  is_enabled: boolean;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreate {
  provider: string;
  label: string;
  api_key: string;
}

export interface ApiKeyUpdate {
  label?: string;
  api_key?: string;
}

export interface ThemeConfig {
  theme: string;
  glassmorphic: boolean;
  primary_color: string;
  background_blur: string;
  border_opacity: number;
}

export interface ModelMetadata {
  model_name: string;
  provider: string;
  accessible: boolean;
  admin_disabled?: boolean;
  deprecated: boolean;
  preview: boolean;
  experimental: boolean;
  enterprise_only: boolean;
  region_supported: boolean;
  context_window?: number;
  input_cost?: number;
  output_cost?: number;
  supports_streaming: boolean;
  supports_function_calling: boolean;
  supports_vision: boolean;
  supports_reasoning: boolean;
  status: string;
  validation_timestamp: string;
}

// BYOK Orchestrator types
export interface Provider {
  id: string;
  name: string;
  display_name: string;
  slug: string;
  litellm_provider: string;
  api_key_prefix: string | null;
  api_key_min_length: number;
  default_model: string;
  timeout_seconds: number;
  max_retries: number;
  priority: number;
  supports_streaming: boolean;
  supports_vision: boolean;
  supports_function_calling: boolean;
  supports_reasoning: boolean;
  is_enabled: boolean;
  status: string;
  status_message: string | null;
  status_expires_at: string | null;
  allow_key_addition: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface DiscoveredModel {
  id: string;
  provider_slug: string;
  model_id: string;
  display_name: string;
  context_window: number | null;
  is_free: boolean;
  description: string | null;
  last_synced_at: string;
}

export interface ProviderHealth {
  id: string;
  provider: string;
  status: string;
  avg_latency_ms: number;
  success_rate: number;
  error_rate: number;
  total_requests: number;
  failed_requests: number;
  circuit_state: string;
  circuit_opened_at: string | null;
  consecutive_failures: number;
  last_error: string | null;
  last_error_at: string | null;
}

export interface ApiKeyHealth {
  id: string;
  key_id: string;
  status: string;
  error_type: string | null;
  error_message: string | null;
  latency_ms: number | null;
  checked_at: string;
}

export interface UsageSummary {
  period: string;
  total_cost_usd: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  request_count: number;
  by_provider: Record<string, number>;
  by_model: Record<string, number>;
  by_feature: Record<string, number>;
}

export interface DailyCost {
  date: string;
  cost_usd: number;
  tokens: number;
}

export interface UsageRecord {
  id: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost_usd: number;
  feature: string;
  latency_ms: number;
  is_fallback: boolean;
  created_at: string;
}

export interface CostBudget {
  id: string;
  user_id: string;
  budget_type: string;
  limit_usd: number;
  spent_usd: number;
  provider: string | null;
  feature: string | null;
  is_active: boolean;
  reset_at: string | null;
}

export interface FailoverLog {
  id: string;
  user_id: string;
  feature: string;
  failed_provider: string;
  failed_model: string;
  failure_reason: string;
  fallback_provider: string;
  fallback_model: string;
  attempt_number: number;
  total_latency_ms: number;
  created_at: string;
}

export interface LLMRequestLog {
  id: string;
  request_id: string;
  provider: string;
  model: string;
  feature: string;
  status: string;
  error_type: string | null;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  was_fallback: boolean;
  attempt_number: number;
  started_at: string;
}

export interface ModelRoute {
  provider: string;
  model: string;
  litellm_model: string;
  api_key_id: string | null;
  estimated_cost_per_1k: number;
}

export interface HealthDashboard {
  providers: ProviderHealth[];
  recent_failovers: FailoverLog[];
  circuit_breakers: Record<string, string>;
}

export interface CostBudgetCreate {
  budget_type: string;
  limit_usd: number;
  provider?: string;
  feature?: string;
}

export interface LLMExecuteRequest {
  messages: Array<{ role: string; content: string }>;
  feature?: string;
  preferred_provider?: string;
  preferred_model?: string;
  api_key_id?: string;
}

export interface LLMExecuteResponse {
  content: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  estimated_cost_usd: number;
  is_fallback: boolean;
}

export interface RepoGithubStats {
  stars: number;
  forks: number;
  open_issues: number;
  contributors: number;
  owner_avatar_url: string | null;
  homepage: string | null;
  topics: string[];
  watchers: number;
}

export interface UsageFilters {
  provider?: string;
  api_key_id?: string;
  model?: string;
  repo_id?: string;
  start_date?: string;
  end_date?: string;
}

const buildFilterQuery = (filters?: UsageFilters) => {
  if (!filters) return '';
  const params = new URLSearchParams();
  if (filters.provider) params.append('provider', filters.provider);
  if (filters.api_key_id) params.append('api_key_id', filters.api_key_id);
  if (filters.model) params.append('model', filters.model);
  if (filters.repo_id) params.append('repo_id', filters.repo_id);
  if (filters.start_date) params.append('start_date', filters.start_date);
  if (filters.end_date) params.append('end_date', filters.end_date);
  const q = params.toString();
  return q ? `&${q}` : '';
};

export const api = {
  // Repository Lifecycle
  refreshInstallation: () => apiClient.post<{ status: string; message: string; new_count: number; removed_count: number; updated_count: number; synced: string[] }>('/repositories/refresh-installation').then((r) => r.data),
  getRepositoryStatus: (id: string) => apiClient.get<{ id: string; full_name: string; status: string; reviews_enabled: boolean; last_synced_at: string | null; settings: Record<string, unknown>; permissions: Record<string, unknown> }>(`/repositories/${id}/status`).then((r) => r.data),

  // Review Lifecycle
  rerunReview: (id: string) => apiClient.post<{ status: string; message: string; new_review_id: string }>(`/reviews/${id}/rerun`).then((r) => r.data),
  retryReview: (id: string) => apiClient.post<{ status: string; message: string; new_review_id: string }>(`/reviews/${id}/retry`).then((r) => r.data),
  restartReview: (id: string) => apiClient.post<{ status: string; message: string; new_review_id: string }>(`/reviews/${id}/restart`).then((r) => r.data),
  getReviewHistory: (id: string) =>
    apiClient
      .get<{
        current_review_id: string;
        current_status: string;
        history: Review[];
        executions: ReviewExecution[];
      }>(`/reviews/${id}/history`)
      .then((r) => r.data),
  getReviewTimeline: (id: string) => apiClient.get<{ review_id: string; timeline: Array<{ id: string; stage: string; status: string; started_at: string | null; completed_at: string | null; duration_ms: number | null; message: string | null; metrics: Record<string, unknown> }> }>(`/reviews/${id}/timeline`).then((r) => r.data),

  // Existing
  getStats: () => apiClient.get<DashboardStats>('/dashboard/stats').then((r) => r.data),
  getReviews: (limit = 20) => apiClient.get<Review[]>(`/reviews?limit=${limit}`).then((r) => r.data),
  getReview: (id: string) => apiClient.get<Review>(`/reviews/${id}`).then((r) => r.data),
  cancelReview: (id: string) => apiClient.post<{ status: string; message: string }>(`/reviews/${id}/cancel`).then((r) => r.data),
  getRepositories: (includeRemoved = false) =>
    apiClient.get<Repository[]>('/repositories', { params: { include_removed: includeRemoved } }).then((r) => r.data),
  getSyncRuns: (limit = 50) =>
    apiClient.get<SyncRun[]>('/repositories/sync-runs', { params: { limit } }).then((r) => r.data),
  syncRepository: (id: string) => apiClient.post<{ status: string; message: string }>(`/repositories/${id}/sync`).then((r) => r.data),
  syncAllRepositories: () => apiClient.post<{ status: string; message: string }>('/repositories/sync-all').then((r) => r.data),
  getRepoGithubStats: (id: string) => apiClient.get<RepoGithubStats>(`/repositories/${id}/github-stats`).then((r) => r.data),
  getApiKeys: () => apiClient.get<ApiKey[]>('/api-keys').then((r) => r.data),
  createApiKey: (data: ApiKeyCreate) => apiClient.post<ApiKey>('/api-keys', data).then((r) => r.data),
  updateApiKey: (id: string, data: ApiKeyUpdate) => apiClient.put<ApiKey>(`/api-keys/${id}`, data).then((r) => r.data),
  deleteApiKey: (id: string) => apiClient.delete<void>(`/api-keys/${id}`).then((r) => r.data),
  testApiKey: (id: string) => apiClient.post<{ status: string; message: string; error_type?: string | null }>(`/api-keys/${id}/test`).then((r) => r.data),
  getThemeConfig: () => apiClient.get<ThemeConfig>('/ui/settings/theme').then((r) => r.data),
  validateForm: (data: { provider: string; api_key: string; label: string }) =>
    apiClient.post<{ valid: boolean; errors: Record<string, string> }>('/ui/settings/validate-form', data).then((r) => r.data),
  getAvailableModels: () =>
    apiClient.get<Record<string, ModelMetadata[]>>(
      '/repositories/available-models',
      // Live provider probing on the backend can run well past 15s with
      // several keys (each provider is a separate network round-trip);
      // keep a generous cap so a stuck request can't spin forever.
      { timeout: 90_000 },
    ).then((r) => r.data),
  updateRepositoryConfig: (id: string, config: { assigned_provider?: string; assigned_model?: string; assigned_key_id?: string; reviews_enabled?: boolean }) =>
    apiClient.patch<Repository>(`/repositories/${id}/config`, config).then((r) => r.data),
  getAuthConfig: () => apiClient.get<{ github_client_id: string }>('/auth/config').then((r) => r.data),

  // OAuth login-CSRF state (single-use; verified at POST /auth/github)
  startOAuthState: () => apiClient.get<{ state: string }>('/auth/oauth/start').then((r) => r.data),

  // API Keys - Enhanced
  rotateApiKey: (id: string, newKey: string) =>
    apiClient.post<ApiKey>(`/api-keys/${id}/rotate`, { api_key: newKey }).then((r) => r.data),
  validateAllKeys: () =>
    apiClient.post<{
      results: Record<string, { status: string; message: string; error_type?: string | null }>;
      summary: { total: number; succeeded: number; failed: number; busy: number };
    }>(
      '/api-keys/validate-all',
      {},
      // Bulk validation runs bounded sequential per-key checks server-side
      // (~22s per key worst case); keep the 100s cap so legitimate
      // multi-key runs don't get truncated by browser or proxy limits.
      { timeout: 100000 },
    ).then((r) => r.data),
  getKeyHealth: (id: string) =>
    apiClient.get<ApiKeyHealth[]>(`/api-keys/${id}/health`).then((r) => r.data),

  // Providers
  getProviders: () => apiClient.get<Provider[]>('/providers').then((r) => r.data),
  getProvider: (slug: string) => apiClient.get<Provider>(`/providers/${slug}`).then((r) => r.data),
  updateProvider: (slug: string, data: Partial<Provider>) =>
    apiClient.put<Provider>(`/providers/${slug}`, data).then((r) => r.data),
  toggleProvider: (slug: string, enabled: boolean) =>
    apiClient.post<Provider>(`/providers/${slug}/toggle`, { is_enabled: enabled }).then((r) => r.data),
  getProviderCapabilities: () =>
    apiClient.get<Record<string, string[]>>('/providers/capabilities').then((r) => r.data),
  syncProviderModels: (slug: string) =>
    apiClient.post<DiscoveredModel[]>(`/providers/${slug}/sync-models`).then((r) => r.data),
  getProviderModels: (slug: string) =>
    apiClient.get<DiscoveredModel[]>(`/providers/${slug}/models`).then((r) => r.data),

  // Usage
  getUsageSummary: (period = 'month', filters?: UsageFilters) =>
    apiClient.get<UsageSummary>(`/platform-usage/summary?period=${period}${buildFilterQuery(filters)}`).then((r) => r.data),
  getUsageTrend: (days = 30, filters?: UsageFilters) =>
    apiClient.get<DailyCost[]>(`/platform-usage/trend?days=${days}${buildFilterQuery(filters)}`).then((r) => r.data),
  getUsageBreakdown: (period = 'month', filters?: UsageFilters) =>
    apiClient.get<Record<string, unknown>>(`/platform-usage/breakdown?period=${period}${buildFilterQuery(filters)}`).then((r) => r.data),
  getUsageRecords: (limit = 50, offset = 0, filters?: UsageFilters) =>
    apiClient.get<UsageRecord[]>(`/platform-usage/records?limit=${limit}&offset=${offset}${buildFilterQuery(filters)}`).then((r) => r.data),

  // Budgets
  getBudgets: () => apiClient.get<CostBudget[]>('/platform-usage/budgets').then((r) => r.data),
  createBudget: (data: { budget_type: string; limit_usd: number; provider?: string; feature?: string }) =>
    apiClient.post<CostBudget>('/platform-usage/budgets', data).then((r) => r.data),
  updateBudget: (id: string, data: Partial<CostBudget>) =>
    apiClient.put<CostBudget>(`/platform-usage/budgets/${id}`, data).then((r) => r.data),
  deleteBudget: (id: string) =>
    apiClient.delete<void>(`/platform-usage/budgets/${id}`).then((r) => r.data),

  // Health
  getProviderHealth: () => apiClient.get<ProviderHealth[]>('/health/providers').then((r) => r.data),
  getProviderHealthDetail: (slug: string) =>
    apiClient.get<ProviderHealth>(`/health/providers/${slug}`).then((r) => r.data),
  checkProviderHealth: (slug: string) =>
    apiClient.post<{ provider: string; status: string; circuit_state: string }>(`/health/providers/${slug}/check`).then((r) => r.data),
  getFailovers: () => apiClient.get<FailoverLog[]>('/health/failovers').then((r) => r.data),
  getCircuitBreakers: () => apiClient.get<Record<string, string>>('/health/circuit-breakers').then((r) => r.data),

  // Routing
  getRoutes: (feature = 'code_review') =>
    apiClient.get<{ routes: ModelRoute[] }>(`/routing/routes?feature=${feature}`).then((r) => r.data),
  recommendRoute: (feature: string) =>
    apiClient.get<ModelRoute>(`/routing/recommend/${feature}`).then((r) => r.data),
  getRoutingPreferences: () =>
    apiClient.get<{ routing: Record<string, { provider: string; model: string }> }>('/routing/preferences').then((r) => r.data),
  updateRoutingPreferences: (routing: Record<string, { provider: string; model: string }>) =>
    apiClient.put<{ status: string; routing: Record<string, { provider: string; model: string }> }>('/routing/preferences', { routing }).then((r) => r.data),
  getModelsPerProvider: () =>
    apiClient.get<Record<string, Array<{model: string; litellm_model: string}>>>(
      '/routing/models-per-provider',
      // Same live-probe path as getAvailableModels — generous per-call cap.
      { timeout: 90_000 },
    ).then((r) => r.data),

  // Analytics
  getRequestLogs: (limit = 50, offset = 0, filters?: UsageFilters) => {    let query = `/platform-analytics/requests?limit=${limit}&offset=${offset}`;
    if (filters) {
        query += buildFilterQuery(filters);
    }
    return apiClient.get<LLMRequestLog[]>(query).then((r) => r.data);
  },
  getErrorSummary: (filters?: UsageFilters) => {
    let query = '/platform-analytics/errors';
    if (filters) {
        query += `?${buildFilterQuery(filters).substring(1)}`;
    }
    return apiClient.get<{ total_errors: number; by_type: Record<string, number>; by_provider: Record<string, number>; error_rate: number }>(query).then((r) => r.data);
  },
  getLatencyStats: (filters?: UsageFilters) => {
    let query = '/platform-analytics/latency';
    if (filters) {
        query += `?${buildFilterQuery(filters).substring(1)}`;
    }
    return apiClient.get<Record<string, number>>(query).then((r) => r.data);
  },
  getFeatureUsage: (filters?: UsageFilters) => {
    let query = '/platform-analytics/features';
    if (filters) {
        query += `?${buildFilterQuery(filters).substring(1)}`;
    }
    return apiClient.get<Array<{ feature: string; request_count: number; total_cost_usd: number; total_tokens: number; avg_latency_ms: number }>>(query).then((r) => r.data);
  },
  getProviderComparison: (filters?: UsageFilters) => {
    let query = '/platform-analytics/providers';
    if (filters) {
        query += `?${buildFilterQuery(filters).substring(1)}`;
    }
    return apiClient.get<Array<{ provider: string; request_count: number; success_rate: number; avg_latency_ms: number; total_cost_usd: number; total_tokens: number }>>(query).then((r) => r.data);
  },

  // Platform status (public, unauthenticated): maintenance state, feature
  // flags and blocked-provider explanations.
  getPlatformStatus: () =>
    apiClient.get<PublicPlatformStatus>('/platform/status').then((r) => r.data),

  // Feature flags (public): status + admin message per key — powers the
  // dashboard gating wrappers and sidebar hiding (§11.1).
  getPlatformFeatures: () =>
    apiClient.get<PlatformFeatures>('/platform/features').then((r) => r.data),

  // Phase 7 — public announcement feed (published + active only).
  getAnnouncements: () =>
    apiClient.get<PublicAnnouncementRead[]>('/platform/announcements').then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Admin console API (isolated server-side session: revora_admin_session cookie)
// ---------------------------------------------------------------------------
export interface AdminSessionInfo {
  username: string;
  expires_at: string;
}

export interface ScalarMetric {
  available: boolean;
  value: number | string | null;
  reason: string | null;
}

export interface NumericMetric {
  available: boolean;
  value: number | null;
  reason: string | null;
  sample_size: number | null;
}

export interface AdminPeriodRead {
  key: string;
  start: string;
  end: string;
}

export interface AdminCredentialBreakdown {
  provider: string;
  total: number;
  valid: number;
  invalid: number;
  enabled: number;
  disabled: number;
}

export interface AdminProviderModelCount {
  provider: string | null;
  model: string | null;
  count: number;
}

export interface AdminFailureCategory {
  category: string;
  count: number;
}

export interface AdminProviderHealthRead {
  provider: string;
  status: string;
  success_rate: number | null;
  circuit_state: string | null;
  last_error: string | null;
  last_error_at: string | null;
  snapshot_at: string | null;
}

export interface AdminMaintenanceState {
  enabled: boolean;
  title: string | null;
  message: string | null;
  expected_return_at: string | null;
}

export interface AdminMaintenanceFull extends AdminMaintenanceState {
  reason: string | null;
  changed_by: string | null;
  changed_at: string | null;
  version: number;
}

export interface AdminMaintenanceUpdate {
  enabled?: boolean;
  title?: string | null;
  message?: string | null;
  expected_return_at?: string | null;
  reason?: string | null;
  version?: number;
}

export interface PublicMaintenanceState {
  enabled: boolean;
  title: string | null;
  message: string | null;
  expected_return_at: string | null;
}

export interface DisabledProviderRead {
  slug: string;
  message: string | null;
  expires_at: string | null;
}

export interface PublicPlatformStatus {
  maintenance: PublicMaintenanceState;
  features: Record<string, string>;
  disabled_providers: DisabledProviderRead[];
}

export interface PublicAnnouncementRead {
  id: string;
  title: string;
  message: string;
  kind: string;
  starts_at: string | null;
  ends_at: string | null;
  link_url: string | null;
  link_label: string | null;
  is_dismissible: boolean;
}

export interface AdminAnnouncementRead {
  id: string;
  title: string;
  message: string;
  kind: string;
  state: string;
  starts_at: string | null;
  ends_at: string | null;
  link_url: string | null;
  link_label: string | null;
  is_enabled: boolean;
  is_dismissible: boolean;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AdminAnnouncementCreate {
  title: string;
  message: string;
  kind?: string;
  starts_at?: string | null;
  ends_at?: string | null;
  link_url?: string | null;
  link_label?: string | null;
  is_enabled?: boolean | null;
  is_dismissible?: boolean | null;
}

export interface AdminAnnouncementUpdate {
  title?: string | null;
  message?: string | null;
  kind?: string | null;
  state?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
  link_url?: string | null;
  link_label?: string | null;
  is_enabled?: boolean | null;
  is_dismissible?: boolean | null;
}

export interface AdminAuditLogItem {
  id: string;
  actor_id: string | null;
  actor_type: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  outcome: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface AdminAuditListResponse {
  items: AdminAuditLogItem[];
  total: number;
}

export const ANNOUNCEMENT_KINDS = [
  'scheduled_maintenance',
  'upgrade',
  'service_interruption',
  'new_feature',
  'provider_update',
  'general',
] as const;

export interface PublicFeatureState {
  status: string;
  message: string | null;
}

export type PlatformFeatures = Record<string, PublicFeatureState>;

export interface AdminFeatureFlag {
  key: string;
  status: string;
  message: string | null;
}

export interface AdminModelOverride {
  provider_slug: string;
  model_id: string;
  status: string;
  message: string | null;
}

export interface AdminModelOverrideUpdate {
  provider_slug: string;
  model_id: string;
  status: string;
  message?: string | null;
}

export interface AdminOverview {
  period: AdminPeriodRead;
  users_total: number;
  users_new_in_period: number;
  signed_in_users: ScalarMetric;
  last_login_at: ScalarMetric;
  active_users: Record<string, ScalarMetric>;
  credentials_total: number;
  credentials_by_provider: AdminCredentialBreakdown[];
  repos_connected: number;
  reviews_total: number;
  reviews_in_period: number;
  reviews_by_status: Record<string, number>;
  reviews_by_provider_model: AdminProviderModelCount[];
  retries_in_period: number;
  duration_p50_ms: NumericMetric;
  duration_p95_ms: NumericMetric;
  failure_rate: NumericMetric;
  failure_categories: AdminFailureCategory[];
  provider_health: AdminProviderHealthRead[];
  maintenance: AdminMaintenanceState;
  features: Record<string, string>;
  token_usage: ScalarMetric;
  cost_totals: ScalarMetric;
}

export type AdminUserStatusFilter = 'active' | 'disabled';

export interface AdminUserListItem {
  id: string;
  name: string;
  email: string;
  github_username: string | null;
  created_at: string;
  last_login_at: string | null;
  status: string;
  repo_count: number;
  credential_count: number;
  review_count: number;
}

export interface AdminUserList {
  items: AdminUserListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminUserRepository {
  id: string;
  full_name: string;
  is_private: boolean;
  is_archived: boolean;
  removed_at: string | null;
  last_synced_at: string | null;
  mapping_provider: string | null;
  mapping_model: string | null;
  mapping_health: string;
}

export interface AdminUserCredential {
  id: string;
  label: string;
  provider: string;
  is_valid: boolean;
  is_enabled: boolean;
  last_used_at: string | null;
  created_at: string;
  last_health_status: string | null;
  last_health_at: string | null;
}

export interface AdminUserReview {
  id: string;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  repository_full_name: string;
  pr_number: number;
  pr_title: string;
  latest_provider: string | null;
  latest_model: string | null;
  latest_status: string | null;
  latest_duration_ms: number | null;
  latest_error: string | null;
}

export interface AdminUserError {
  provider: string | null;
  message: string;
  occurred_at: string | null;
}

export interface AdminAuditEvent {
  id: string;
  action: string;
  actor_id: string | null;
  actor_type: string;
  outcome: string | null;
  created_at: string;
}

export interface AdminUserProfile {
  id: string;
  name: string;
  email: string;
  github_username: string | null;
  avatar_url: string | null;
  role: string;
  status: string;
  is_verified: boolean;
  default_provider: string | null;
  created_at: string;
  disabled_at: string | null;
  last_login_at: string | null;
  last_active_at: string | null;
}

export interface AdminUserDetail {
  profile: AdminUserProfile;
  repositories: AdminUserRepository[];
  credentials: AdminUserCredential[];
  reviews: {
    items: AdminUserReview[];
    total: number;
    status_counts: Record<string, number>;
  };
  recent_errors: AdminUserError[];
  audit_events: AdminAuditEvent[];
}

export interface AdminUserStatus {
  id: string;
  status: string;
  disabled_at: string | null;
}

export interface AdminRepositoryItem {
  id: string;
  full_name: string;
  is_private: boolean;
  is_archived: boolean;
  removed_at: string | null;
  created_at: string;
  last_synced_at: string | null;
  owner_id: string;
  owner_email: string;
  owner_github_username: string | null;
  installation_account_login: string | null;
  installation_suspended_at: string | null;
  installation_permissions_ok: boolean | null;
  mapping_provider: string | null;
  mapping_model: string | null;
  mapping_health: string;
  review_count: number;
  last_review_at: string | null;
  recent_failures_7d: number;
}

export interface AdminRepositoryList {
  items: AdminRepositoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminReviewItem {
  id: string;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  repository_id: string;
  repository_full_name: string;
  pr_number: number;
  pr_title: string;
  owner_email: string;
  configured_provider: string | null;
  configured_model: string | null;
  provider: string | null;
  model: string | null;
  execution_status: string | null;
  duration_ms: number | null;
  error: string | null;
}

export interface AdminReviewList {
  items: AdminReviewItem[];
  total: number;
  limit: number;
  offset: number;
}

// Phase 4 — provider / credential controls
export interface AdminProviderRead {
  id: string;
  name: string;
  display_name: string;
  slug: string;
  default_model: string;
  priority: number;
  is_enabled: boolean;
  status: string;
  status_message: string | null;
  status_expires_at: string | null;
  allow_key_addition: boolean;
  supports_streaming: boolean;
  supports_vision: boolean;
  supports_function_calling: boolean;
  supports_reasoning: boolean;
  keys_total: number;
  keys_enabled: number;
  keys_valid: number;
  mapped_repositories: number;
  models_count?: number;
  last_health_status: string | null;
  last_health_at: string | null;
}

export interface AdminProviderList {
  items: AdminProviderRead[];
}

export interface AdminProviderUpdate {
  status?: string;
  status_message?: string | null;
  status_expires_at?: string | null;
  is_enabled?: boolean;
  allow_key_addition?: boolean;
}

export interface AdminKeyRead {
  id: string;
  user_id: string;
  user_email: string;
  provider: string;
  label: string;
  is_valid: boolean;
  is_enabled: boolean;
  last_used_at: string | null;
  created_at: string | null;
}

export interface AdminKeyList {
  items: AdminKeyRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminKeyListParams {
  user_id?: string;
  provider?: string;
  limit?: number;
  offset?: number;
}

export interface AdminUserListParams {
  q?: string;
  status?: AdminUserStatusFilter;
  sort?: 'created' | 'last_login' | 'reviews';
  limit?: number;
  offset?: number;
}

export interface AdminRepositoryListParams {
  user?: string;
  provider?: string;
  mapping?: 'ok' | 'stale' | 'missing';
  limit?: number;
  offset?: number;
}

export interface AdminReviewListParams {
  user?: string;
  repo?: string;
  provider?: string;
  model?: string;
  status?: string;
  error?: string;
  period?: '24h' | '7d' | '30d';
  start?: string;
  end?: string;
  limit?: number;
  offset?: number;
}

export const adminApi = {
  login: (data: { username: string; password: string }) =>
    apiClient.post<AdminSessionInfo>('/admin/auth/login', data).then((r) => r.data),
  session: () =>
    apiClient.get<AdminSessionInfo>('/admin/auth/session').then((r) => r.data),
  logout: () =>
    apiClient.post<{ status: string }>('/admin/auth/logout').then((r) => r.data),

  // Phase 2 — read-only analytics
  overview: (params?: { period?: string; start?: string; end?: string }) =>
    apiClient.get<AdminOverview>('/admin/overview', { params }).then((r) => r.data),
  users: (params?: AdminUserListParams) =>
    apiClient.get<AdminUserList>('/admin/users', { params }).then((r) => r.data),
  user: (id: string, params?: { reviews_limit?: number; reviews_offset?: number }) =>
    apiClient.get<AdminUserDetail>(`/admin/users/${id}`, { params }).then((r) => r.data),
  disableUser: (id: string, data: { reason: string }) =>
    apiClient.post<AdminUserStatus>(`/admin/users/${id}/disable`, data).then((r) => r.data),
  enableUser: (id: string) =>
    apiClient.post<AdminUserStatus>(`/admin/users/${id}/enable`).then((r) => r.data),
  revokeUserSessions: (id: string) =>
    apiClient
      .post<{ revoked: boolean }>(`/admin/users/${id}/revoke-sessions`)
      .then((r) => r.data),
  repositories: (params?: AdminRepositoryListParams) =>
    apiClient.get<AdminRepositoryList>('/admin/repositories', { params }).then((r) => r.data),
  reviews: (params?: AdminReviewListParams) =>
    apiClient.get<AdminReviewList>('/admin/reviews', { params }).then((r) => r.data),

  // Phase 4 — provider / credential controls
  providers: () =>
    apiClient.get<AdminProviderList>('/admin/providers').then((r) => r.data),
  updateProvider: (slug: string, data: AdminProviderUpdate) =>
    apiClient.put<AdminProviderRead>(`/admin/providers/${slug}`, data).then((r) => r.data),
  keys: (params?: AdminKeyListParams) =>
    apiClient.get<AdminKeyList>('/admin/keys', { params }).then((r) => r.data),
  disableKey: (id: string) =>
    apiClient.post<AdminKeyRead>(`/admin/keys/${id}/disable`).then((r) => r.data),
  enableKey: (id: string) =>
    apiClient.post<AdminKeyRead>(`/admin/keys/${id}/enable`).then((r) => r.data),

  // Phase 5 — maintenance mode
  maintenance: () =>
    apiClient.get<AdminMaintenanceFull>('/admin/maintenance').then((r) => r.data),
  updateMaintenance: (data: AdminMaintenanceUpdate) =>
    apiClient
      .put<AdminMaintenanceFull>('/admin/maintenance', data)
      .then((r) => r.data),

  // Phase 6 — feature flags / model overrides
  features: () =>
    apiClient.get<AdminFeatureFlag[]>('/admin/features').then((r) => r.data),
  updateFeature: (key: string, data: { status: string; message?: string | null }) =>
    apiClient
      .put<AdminFeatureFlag>(`/admin/features/${key}`, data)
      .then((r) => r.data),
  modelOverrides: () =>
    apiClient.get<AdminModelOverride[]>('/admin/models/overrides').then((r) => r.data),
  updateModelOverride: (data: AdminModelOverrideUpdate) =>
    apiClient
      .put<AdminModelOverride>('/admin/models/overrides', data)
      .then((r) => r.data),

  // Phase 7 — announcements
  announcements: () =>
    apiClient.get<AdminAnnouncementRead[]>('/admin/announcements').then((r) => r.data),
  createAnnouncement: (data: AdminAnnouncementCreate) =>
    apiClient.post<AdminAnnouncementRead>('/admin/announcements', data).then((r) => r.data),
  updateAnnouncement: (id: string, data: AdminAnnouncementUpdate) =>
    apiClient.put<AdminAnnouncementRead>(`/admin/announcements/${id}`, data).then((r) => r.data),
  deleteAnnouncement: (id: string) =>
    apiClient.delete<void>(`/admin/announcements/${id}`).then((r) => r.data),

  // Phase 7 — audit log viewer
  audit: (params?: {
    action?: string;
    actor?: string;
    entity_type?: string;
    period?: string;
    start?: string;
    end?: string;
    limit?: number;
    offset?: number;
  }) =>
    apiClient
      .get<AdminAuditListResponse>('/admin/audit', { params })
      .then((r) => r.data),
};

export interface MouthMapConfig {
  model: string;
  model_version: string;
  input_frames: number;
  input_resolution: string;
  provider: string;
  compute: string;
  max_upload_mb: number;
  allowed_extensions: string[];
}

export interface MouthMapTestVideo {
  id: string;
  filename: string;
  duration_s: number | null;
  resolution: string | null;
  size_bytes: number | null;
  ground_truth: string | null;
  has_alignment: boolean;
  status: string;
}

export interface MouthMapInferenceResult {
  prediction: string;
  model: string;
  model_version: string | null;
  confidence: number | null;
  inference_time_ms: number | null;
  frames_processed: number | null;
  status: string;
  expected: string | null;
  is_match: boolean | null;
  raw: Record<string, unknown>;
}

export interface MouthMapHistoryItem {
  id: string;
  video_filename: string;
  source: string;
  test_video_id: string | null;
  prediction: string | null;
  expected: string | null;
  is_match: boolean | null;
  confidence: number | null;
  inference_time_ms: number | null;
  frames_processed: number | null;
  model_version: string | null;
  status: string;
  created_at: string | null;
}

export const mouthmapApi = {
  getConfig: () => apiClient.get<MouthMapConfig>('/mouthmap/config').then((r) => r.data),
  getHealth: () =>
    apiClient.get<{ status: string; endpoint: string; detail: string | null }>('/mouthmap/health').then((r) => r.data),
  // Wake the hosted HF Space and confirm readiness. Called on demand when a
  // run starts (never on page load). The backend holds the request while the
  // Space boots, bounded by MOUTHMAP_WAKE_TIMEOUT_S; a warm Space returns fast.
  warm: (opts?: { signal?: AbortSignal }) =>
    apiClient
      .post<{ status: string }>('/mouthmap/warm', null, { timeout: 200000, signal: opts?.signal })
      .then((r) => r.data),
  getDataset: () => apiClient.get<MouthMapTestVideo[]>('/mouthmap/dataset').then((r) => r.data),
  streamUrl: (id: string) => `${API_BASE}/mouthmap/dataset/${encodeURIComponent(id)}/stream`,
  runInference: (file: Blob, filename: string, opts?: { test_video_id?: string; source?: string; signal?: AbortSignal }, onUploadProgress?: (pct: number, uploadComplete: boolean) => void) => {
    const form = new FormData();
    form.append('video', file, filename);
    if (opts?.test_video_id) form.append('test_video_id', opts.test_video_id);
    form.append('source', opts?.source ?? 'upload');
    return apiClient
      .post<MouthMapInferenceResult>('/mouthmap/inference', form, {
        // Do NOT set Content-Type manually: the browser must generate the
        // multipart boundary automatically. A hardcoded
        // 'multipart/form-data' header (without boundary) makes FastAPI
        // reject the request at form parsing, before it reaches the endpoint.
        // axios's default 'application/json' header is overridden here by
        // deleting it so the browser/XHR sets the correct multipart header.
        transformRequest: [(data, headers) => {
          const h = headers as unknown as {
            delete?: (k: string) => void;
          };
          if (typeof h?.delete === 'function') h.delete('Content-Type');
          else if (headers) delete (headers as Record<string, unknown>)['Content-Type'];
          return data;
        }],
        timeout: 200000,
        signal: opts?.signal,
        onUploadProgress: (e) => {
          if (onUploadProgress && e.total) {
            // uploadComplete is observed from the raw XHR event (all bytes
            // delivered) — never inferred from elapsed time or animation.
            onUploadProgress(Math.round((e.loaded / e.total) * 100), e.loaded >= e.total);
          }
        },
      })
      .then((r) => r.data);
  },
  getHistory: (limit = 20, offset = 0) =>
    apiClient.get<MouthMapHistoryItem[]>(`/mouthmap/history?limit=${limit}&offset=${offset}`).then((r) => r.data),
};






