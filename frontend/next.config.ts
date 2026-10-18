import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server build for Dockerfile.frontend (NEXT_OUTPUT=standalone);
  // a normal build keeps `npm start` working for local runs.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // Pin the workspace root to this folder so a stray lockfile higher up the
  // filesystem is never picked as the project root.
  turbopack: {
    root: path.resolve(__dirname),
  },
  outputFileTracingRoot: path.resolve(__dirname),
};

export default nextConfig;
