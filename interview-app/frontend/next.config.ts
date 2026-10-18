import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "*.cloudfront.net" },
      { protocol: "https", hostname: "d*.cloudfront.net" },
      { protocol: "https", hostname: "res.cloudinary.com" },
      { protocol: "https", hostname: "lh3.googleusercontent.com" },
      { protocol: "https", hostname: "avatars.githubusercontent.com" },
      { protocol: "https", hostname: "ui-avatars.com" },
    ],
  },
  async rewrites() {
    const backendUrl = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";
    return [
      {
        source: '/api/backend/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
  async redirects() {
    return [
      {
        source: '/signup',
        destination: '/login?mode=signup',
        permanent: false,
      },
      {
        source: '/system-design',
        destination: '/courses/system-design',
        permanent: true,
      },
      {
        source: '/genai-system-design',
        destination: '/courses/genai-system-design',
        permanent: true,
      },
      {
        source: '/ml-system-design',
        destination: '/courses/ml-system-design',
        permanent: true,
      },
      {
        source: '/mobile-system-design',
        destination: '/courses/mobile-system-design',
        permanent: true,
      },
      {
        source: '/object-oriented-design',
        destination: '/courses/object-oriented-design',
        permanent: true,
      },
      {
        source: '/sql-course',
        destination: '/courses/sql-course',
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
