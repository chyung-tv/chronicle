import type { NextConfig } from "next";

const origin = process.env.PLAYOUT_API_ORIGIN || "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${origin}/api/:path*` }];
  },
};

export default nextConfig;
