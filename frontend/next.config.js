/** @type {import('next').NextConfig} */
// Next config is loaded as CommonJS by the project setup.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const path = require("path");

const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: path.join(__dirname, ".."),
  async rewrites() {
    const backendUrl = process.env.NEXT_SERVER_API_URL ?? "http://127.0.0.1:8000";

    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
