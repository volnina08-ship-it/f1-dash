import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The dashboard is fully client-side with the demo race baked in, so it
  // ships as a static export — deployable on Vercel from the monorepo root
  // (see /vercel.json) or any static host, no server needed.
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
