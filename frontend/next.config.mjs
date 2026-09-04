/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const base = process.env.NEXT_PUBLIC_API_URL
    // If NEXT_PUBLIC_API_URL is relative (/api) or not set, don't rewrite (use same origin /api via nginx)
    // Only rewrite when absolute URL is provided for dev
    if (!base || base.startsWith("/")) return []
    const destBase = base.replace(/\/api\/?$/, "")
    return [
      {
        source: "/api/:path*",
        destination: `${destBase}/api/:path*`,
      },
    ]
  },
  // For docker, API is via same origin reverse proxy
};
export default nextConfig;
