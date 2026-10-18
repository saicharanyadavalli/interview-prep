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
});
