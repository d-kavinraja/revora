import type { NextConfig } from "next";

// Server-only backend origin for the same-origin API proxy (P0-A).
// Deliberately NOT a NEXT_PUBLIC_* var: the browser must never learn the
// backend host. Accepts a bare origin or one ending in /api/v1.
const BACKEND_ORIGIN = (process.env.BACKEND_ORIGIN ?? "")
  .trim()
  .replace(/\/+$/, "")
  .replace(/\/api\/v1$/, "");

const nextConfig: NextConfig = {
  /* config options here */
  devIndicators: false,
  // Same-origin API proxy: the browser calls /api/v1/* on the frontend
  // host (carrying the HttpOnly session cookie) and Next forwards each
  // request to Render untouched (method, query, headers, cookies, body,
  // SSE stream). Registered only when BACKEND_ORIGIN is configured, so
  // local dev keeps its absolute localhost base (same-host cookie already
  // works there). NOTE: /api/auth/* BFF routes are unaffected (different
  // prefix), and the edge matcher (proxy.ts) already excludes /api/*, so
  // proxied calls never hit middleware — no redirect loops.
  async rewrites() {
    if (!BACKEND_ORIGIN) return [];
    return [
      {
        source: "/api/v1/:path*",
        destination: `${BACKEND_ORIGIN}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;