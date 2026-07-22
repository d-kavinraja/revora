import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  devIndicators: false,
  // @ts-ignore - added to bypass HMR blocking for ngrok
  allowedDevOrigins: [
    '90ad-2409-40f4-3140-18d0-e82e-c778-984c-34b9.ngrok-free.app',
    '1605-2409-40f4-3140-18d0-c1b8-6658-ec9e-514b.ngrok-free.app',
    'f3a0-2409-40f4-3140-18d0-c1b8-6658-ec9e-514b.ngrok-free.app'
  ],
};

export default nextConfig;
