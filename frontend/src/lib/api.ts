import axios from 'axios';
import { useAuthStore } from '@/store/useAuthStore';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';

export const apiClient = axios.create({
  baseURL: API_BASE,
  headers: { 
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true'
  },
  timeout: 15000, // 15s timeout to prevent UI freezing on slow/unresponsive backend
});

// Attach JWT token on every request
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-logout on 401
apiClient.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout();
    }
    return Promise.reject(error);
  }
);

export type ReviewStatus = 'pending' | 'running' | 'completed' | 'failed';

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
  pull_request: PullRequestInfo;
  repository: { id?: string; name: string; full_name: string };
}

export interface Repository {
  id: string;
  name: string;
  full_name: string;
  description: string | null;
  language: string | null;
  is_private: boolean;
  reviews_enabled: boolean;
  total_reviews: number;
  last_synced_at: string | null;
  settings?: {
    assigned_provider?: string;
    assigned_model?: string;
    assigned_key_id?: string;
  };
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
  // Existing
  getStats: () => apiClient.get<DashboardStats>('/dashboard/stats').then((r) => r.data),
  getReviews: (limit = 20) => apiClient.get<Review[]>(`/reviews?limit=${limit}`).then((r) => r.data),
  getReview: (id: string) => apiClient.get<Review>(`/reviews/${id}`).then((r) => r.data),
  getRepositories: () => apiClient.get<Repository[]>('/repositories').then((r) => r.data),
  syncRepository: (id: string) => apiClient.post<{ message: string }>(`/repositories/${id}/sync`).then((r) => r.data),
  syncAllRepositories: () => apiClient.post<{ message: string }>('/repositories/sync-all').then((r) => r.data),
  getApiKeys: () => apiClient.get<ApiKey[]>('/api-keys').then((r) => r.data),
  createApiKey: (data: ApiKeyCreate) => apiClient.post<ApiKey>('/api-keys', data).then((r) => r.data),
  updateApiKey: (id: string, data: ApiKeyUpdate) => apiClient.put<ApiKey>(`/api-keys/${id}`, data).then((r) => r.data),
  deleteApiKey: (id: string) => apiClient.delete<void>(`/api-keys/${id}`).then((r) => r.data),
  testApiKey: (id: string) => apiClient.post<{ status: string; message: string }>(`/api-keys/${id}/test`).then((r) => r.data),
  getThemeConfig: () => apiClient.get<ThemeConfig>('/ui/settings/theme').then((r) => r.data),
  validateForm: (data: { provider: string; api_key: string; label: string }) =>
    apiClient.post<{ valid: boolean; errors: Record<string, string> }>('/ui/settings/validate-form', data).then((r) => r.data),
  getAvailableModels: () => apiClient.get<Record<string, ModelMetadata[]>>('/repositories/available-models').then((r) => r.data),
  updateRepositoryConfig: (id: string, config: { assigned_provider?: string; assigned_model?: string; assigned_key_id?: string; reviews_enabled?: boolean }) =>
    apiClient.patch<Repository>(`/repositories/${id}/config`, config).then((r) => r.data),
  getAuthConfig: () => apiClient.get<{ github_client_id: string }>('/auth/config').then((r) => r.data),

  // API Keys - Enhanced
  rotateApiKey: (id: string, newKey: string) =>
    apiClient.post<ApiKey>(`/api-keys/${id}/rotate`, { api_key: newKey }).then((r) => r.data),
  validateAllKeys: () =>
    apiClient.post<{ results: Record<string, { status: string; message: string }> }>('/api-keys/validate-all').then((r) => r.data),
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






