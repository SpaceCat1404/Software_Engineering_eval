/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingRoot: __dirname,
  async rewrites() {
    // Local dev only: `vercel dev` handles /api/* itself, but plain
    // `next dev` doesn't run the Python function, so proxy to a locally
    // running `uvicorn api.index:app` instead.
    if (process.env.NODE_ENV !== "development") return [];
    return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
  },
};

module.exports = nextConfig;
