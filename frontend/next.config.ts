import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: { root: path.resolve(__dirname) },
  poweredByHeader: false,
};

export default nextConfig;
