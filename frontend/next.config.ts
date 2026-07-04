import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.56.1"],
  // Phosphor's barrel exports thousands of icon modules. Without this, dev
  // (Turbopack) compiles the whole barrel on every page that imports an icon -
  // leaving the tab perpetually "loading" (busy cursor). Like the built-in
  // lucide-react optimization, this rewrites barrel imports to direct ones so
  // only the icons actually used are loaded.
  experimental: {
    optimizePackageImports: [
      "@phosphor-icons/react",
      "@phosphor-icons/react/dist/ssr",
    ],
  },
};

export default nextConfig;
