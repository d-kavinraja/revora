import type { NextConfig } from "next";
import { resolveRewriteDestination } from "./src/lib/api-transport";

const nextConfig: NextConfig = {
  /* config options here */
  devIndicators: false,
  experimental: {
    agentUpgrade: "security",
  },
  // Same-origin API proxy. The decision comes from the same module the
  // browser client uses (src/lib/api.ts), so /api/v1 is only used by the
  // browser when this rewrite is actually installed. BACKEND_ORIGIN is
  // server-only: the browser never sees the internal backend host.
  // NOTE: /api/auth/* BFF routes are unaffected (different prefix), and the
  // edge matcher (proxy.ts) already excludes /api/*, so proxied calls never
  // hit middleware — no redirect loops.
  async rewrites() {
    const { useProxy, destination, error } = resolveRewriteDestination();
    if (!useProxy) return [];
    if (error || !destination) {
      throw new Error(error ?? "Invalid /api/v1 rewrite configuration.");
    }
    return [{ source: "/api/v1/:path*", destination }];
  },
};

export default nextConfig;
