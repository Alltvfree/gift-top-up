/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export → deployable to Cloudflare Pages (build output dir: `out`).
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
