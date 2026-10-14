/**
 * Server-side base URL for backend API calls made by BFF route handlers.
 *
 * BACKEND_ORIGIN is a bare origin (e.g. https://revora-faog.onrender.com)
 * while NEXT_PUBLIC_API_URL already includes the /api/v1 suffix. Both
 * shapes are normalized to ".../api/v1" here so handlers never build a
 * bare "/auth/..." upstream URL — FastAPI mounts every router under
 * /api/v1 (see backend/app/main.py) and answers suffix-less paths with
 * 404, which previously broke login/logout the moment BACKEND_ORIGIN
 * was set. Mirrors the normalization in frontend/next.config.ts.
 */
export function backendApiBase(): string {
  const raw =
    process.env.BACKEND_ORIGIN ||
    process.env.NEXT_PUBLIC_API_URL ||
    'http://localhost:8000/api/v1';
  const trimmed = raw.trim().replace(/\/+$/, '');
  return trimmed.endsWith('/api/v1') ? trimmed : `${trimmed}/api/v1`;
}
