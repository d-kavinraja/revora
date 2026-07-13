import axios from 'axios';
import { useAuthStore } from '@/store/useAuthStore';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';

export const apiClient = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
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
  repository: { name: string; full_name: string };
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

export const api = {
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
  getAvailableModels: () => apiClient.get<Record<string, string[]>>('/repositories/available-models').then((r) => r.data),
  updateRepositoryConfig: (id: string, config: { assigned_provider?: string; assigned_model?: string; reviews_enabled?: boolean }) =>
    apiClient.patch<Repository>(`/repositories/${id}/config`, config).then((r) => r.data),
};
