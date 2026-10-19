import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import nextConfig from "../next.config.ts";
import { generateInitialsAvatar } from "../src/utils/avatar-validation.ts";

describe("Next.js Configuration & Remote Patterns", () => {
  it("should configure images remotePatterns", () => {
    assert.ok(nextConfig.images);
    assert.ok(Array.isArray(nextConfig.images.remotePatterns));
  });

  it("should permit CloudFront CDN subdomains via HTTPS", () => {
    const patterns = nextConfig.images?.remotePatterns || [];
    const cloudFrontPattern = patterns.find(
      (p: any) => p.hostname === "*.cloudfront.net" && p.protocol === "https"
    );
    assert.ok(cloudFrontPattern, "Must allow *.cloudfront.net via HTTPS");

    const dCloudFrontPattern = patterns.find(
      (p: any) => p.hostname === "d*.cloudfront.net" && p.protocol === "https"
    );
    assert.ok(dCloudFrontPattern, "Must allow d*.cloudfront.net via HTTPS");
  });

  it("should retain Google and GitHub avatar remote patterns", () => {
    const patterns = nextConfig.images?.remotePatterns || [];
    const googlePattern = patterns.find(
      (p: any) => p.hostname === "lh3.googleusercontent.com" && p.protocol === "https"
    );
    assert.ok(googlePattern, "Must allow Google avatars via lh3.googleusercontent.com");

    const githubPattern = patterns.find(
      (p: any) => p.hostname === "avatars.githubusercontent.com" && p.protocol === "https"
    );
    assert.ok(githubPattern, "Must allow GitHub avatars via avatars.githubusercontent.com");
  });

  it("should retain legacy Cloudinary and UI-avatars fallbacks", () => {
    const patterns = nextConfig.images?.remotePatterns || [];
    const cloudinaryPattern = patterns.find(
      (p: any) => p.hostname === "res.cloudinary.com" && p.protocol === "https"
    );
    assert.ok(cloudinaryPattern, "Must retain res.cloudinary.com for legacy migration compatibility");

    const uiAvatarsPattern = patterns.find(
      (p: any) => p.hostname === "ui-avatars.com" && p.protocol === "https"
    );
    assert.ok(uiAvatarsPattern, "Must retain ui-avatars.com");
  });

  it("should verify CloudFront avatar URLs and fallback initials SVG resolution", () => {
    const cloudFrontUrl = "https://d123456abcdef8.cloudfront.net/avatars/user-42/profile.jpg";
    const name = "Jane Doe";

    // When valid CloudFront URL is provided:
    const effectiveWithUrl = cloudFrontUrl.trim();
    assert.equal(effectiveWithUrl, cloudFrontUrl);
    assert.ok(effectiveWithUrl.startsWith("https://"));

    // When avatar is empty or whitespace:
    const emptyAvatar = "   ";
    const fallbackSrc = generateInitialsAvatar(name, 96);
    const effectiveWithEmpty = (!emptyAvatar || emptyAvatar.trim().length === 0) ? fallbackSrc : emptyAvatar;
    assert.ok(effectiveWithEmpty.startsWith("data:image/svg+xml;utf8,"));
    const decodedSvg = decodeURIComponent(effectiveWithEmpty);
    assert.ok(decodedSvg.includes("JD"));
  });

  it("should configure canonical course redirects from legacy tracks to /courses/:slug", async () => {
    assert.ok(typeof nextConfig.redirects === "function");
    const redirects = await nextConfig.redirects();
    assert.ok(Array.isArray(redirects));

    const expectedRedirects = [
      { source: "/system-design", destination: "/courses/system-design" },
      { source: "/genai-system-design", destination: "/courses/genai-system-design" },
      { source: "/ml-system-design", destination: "/courses/ml-system-design" },
      { source: "/mobile-system-design", destination: "/courses/mobile-system-design" },
      { source: "/object-oriented-design", destination: "/courses/object-oriented-design" },
      { source: "/sql-course", destination: "/courses/sql-course" },
    ];

    for (const expected of expectedRedirects) {
      const match = redirects.find((r: any) => r.source === expected.source);
      assert.ok(match, `Redirect for ${expected.source} must exist`);
      assert.equal(match.destination, expected.destination);
      assert.equal(match.permanent, true);
    }
  });

  it("should NOT configure rewrites that shadow the App Router BFF proxy (/api/backend)", async () => {
    // In Next.js App Router, rewrites shadow dynamic route handlers like app/api/backend/[...path]/route.ts
    // Confirm rewrites() is removed so cookies are forwarded as Authorization Bearer tokens
    if (typeof (nextConfig as any).rewrites === "function") {
      const rewrites = await (nextConfig as any).rewrites();
      const list = Array.isArray(rewrites)
        ? rewrites
        : [
            ...((rewrites as any)?.beforeFiles || []),
            ...((rewrites as any)?.afterFiles || []),
            ...((rewrites as any)?.fallback || []),
          ];
      const backendRewrite = list.find((r: any) => r.source?.includes("/api/backend"));
      assert.equal(backendRewrite, undefined, "rewrites must not shadow /api/backend catch-all route handler");
    } else {
      assert.equal(
        (nextConfig as any).rewrites,
        undefined,
        "rewrites should be undefined to allow App Router BFF proxy to handle /api/backend"
      );
    }
  });
});
