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
  async rewrites() {
    return [
      // Serve the LikeC4 viewer's entry point at a clean /architecture.
      //
      // Next does NOT map a directory in public/ to its index.html: the built
      // viewer answers /architecture/index.html but /architecture is a plain
      // 404, and Next's trailing-slash normalisation redirects /architecture/
      // straight into that 404. One rewrite, scoped to this exact path.
      //
      // Declared here rather than in vercel.json so it also applies to
      // `next dev` and `next start` - a rewrite that only exists on the
      // platform cannot be tested before it is live.
      {
        source: "/architecture",
        destination: "/architecture/index.html",
      },
    ];
  },
};

export default nextConfig;
