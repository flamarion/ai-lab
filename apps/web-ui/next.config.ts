import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Proxy API calls to the gateway in development
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
