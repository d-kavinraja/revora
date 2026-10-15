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
  timeout: 15000, // 15s timeout to prevent UI freezing on slow/unresponsive backend
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
  | { ok: false; reason: 'unauthorized' | 'unreachable' };

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
    const reason = status === 401 || status === 403 ? 'unauthorized' : 'unreachable';
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
    if (error.response?.status === 401) {
      const url =
        typeof error.config?.url === 'string' ? error.config.url : '';
      const isRestore = !!error.config?.__revoraRestore;
      // Public endpoint: no session expected, nothing to clear.
      const isPublic = url.includes('/auth/config');
      const state = useAuthStore.getState();
      const onProtected =
        typeof window !== 'undefined' &&
        isProtectedPath(window.location.pathname);
      // Restore failures belong to the dashboard guard; public endpoints
      // and already-signed-out states need no logout round-trip. Logout
      // itself is single-flighted in the store, so concurrent 401s share
      // one clearing pass instead of stampeding.
      if (!isRestore && !isPublic && state.isAuthenticated) {
        // Await the cookie-clearing logout BEFORE any hard navigation, so the
        // edge gate cannot bounce us straight back to the dashboard.
        void (async () => {
          await useAuthStore.getState().logout({ revoke: false });
          if (
            onProtected &&
            typeof window !== 'undefined' &&
            window.location.pathname !== '/login'
          ) {
            window.location.assign('/login');
          }
        })();
      } else if (
        !state.isAuthenticated &&
        onProtected &&
        typeof window !== 'undefined' &&
        window.location.pathname !== '/login'
      ) {
        window.location.assign('/login');
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
  base_url_template: string | null;
  default_model: string;
  timeout_seconds: number;
  max_retries: number;
  priority: number;
  supports_streaming: boolean;
  supports_vision: boolean;
  supports_function_calling: boolean;
  supports_reasoning: boolean;
  is_enabled: boolean;
  extra_config: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  status?: 'active' | 'archived' | 'deleted' | null;
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
  getAvailableModels: () => apiClient.get<Record<string, ModelMetadata[]>>('/repositories/available-models').then((r) => r.data),
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
      // (~22s per key worst case); use an explicit long timeout instead of
      // the global 15s so legitimate multi-key runs don't false-timeout.
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
    apiClient.get<Record<string, Array<{model: string; litellm_model: string}>>>('/routing/models-per-provider').then((r) => r.data),

  // Analytics
  getRequestLogs: (limit = 50, offset = 0, filters?: UsageFilters) => {
    let query = `/platform-analytics/requests?limit=${limit}&offset=${offset}`;
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






