import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@blocknote/core", "@blocknote/react", "@blocknote/mantine"],
};

export default nextConfig;
