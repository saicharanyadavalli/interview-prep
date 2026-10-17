import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  detectImageMagicBytes,
  generateInitialsAvatar,
  validateAvatarFile,
  MAX_AVATAR_BYTES,
  MIN_AVATAR_DIMENSION,
  MAX_AVATAR_DIMENSION,
  ALLOWED_AVATAR_EXTENSIONS,
  ALLOWED_AVATAR_MIME_TYPES,
} from "../src/utils/avatar-validation.ts";

describe("Avatar Security and Validation Utilities", () => {
  describe("detectImageMagicBytes", () => {
    it("should recognize genuine JPEG magic bytes", () => {
      const buffer = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]).buffer;
      const result = detectImageMagicBytes(buffer);
      assert.equal(result.valid, true);
      assert.equal(result.format, "jpeg");
      assert.equal(result.mime, "image/jpeg");
    });

    it("should recognize genuine PNG magic bytes", () => {
      const buffer = new Uint8Array([
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00,
      ]).buffer;
      const result = detectImageMagicBytes(buffer);
      assert.equal(result.valid, true);
      assert.equal(result.format, "png");
      assert.equal(result.mime, "image/png");
    });

    it("should recognize genuine GIF magic bytes", () => {
      const buffer = new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61]).buffer;
      const result = detectImageMagicBytes(buffer);
      assert.equal(result.valid, true);
      assert.equal(result.format, "gif");
      assert.equal(result.mime, "image/gif");
    });

    it("should recognize genuine WebP magic bytes", () => {
      // RIFF....WEBP
      const buffer = new Uint8Array([
        0x52, 0x49, 0x46, 0x46, // RIFF
        0x20, 0x00, 0x00, 0x00, // file size
        0x57, 0x45, 0x42, 0x50, // WEBP
        0x56, 0x50, 0x38, 0x20, // VP8
      ]).buffer;
      const result = detectImageMagicBytes(buffer);
      assert.equal(result.valid, true);
      assert.equal(result.format, "webp");
      assert.equal(result.mime, "image/webp");
    });

    it("should reject spoofed or corrupted header buffers", () => {
      // Plain text header "Hello world"
      const buffer = new TextEncoder().encode("Hello World, this is not an image").buffer;
      const result = detectImageMagicBytes(buffer);
      assert.equal(result.valid, false);
    });

    it("should reject short buffers under 4 bytes", () => {
      const buffer = new Uint8Array([0xff, 0xd8]).buffer;
      const result = detectImageMagicBytes(buffer);
      assert.equal(result.valid, false);
    });
  });

  describe("generateInitialsAvatar", () => {
    it("should extract initials from two-word full name", () => {
      const dataUri = generateInitialsAvatar("Alice Smith");
      assert.ok(dataUri.startsWith("data:image/svg+xml;utf8,"));
      const decoded = decodeURIComponent(dataUri);
      assert.ok(decoded.includes("AS"));
    });

    it("should extract two-letter initials from single-word username", () => {
      const dataUri = generateInitialsAvatar("developer");
      const decoded = decodeURIComponent(dataUri);
      assert.ok(decoded.includes("DE"));
    });

    it("should fall back to 'U' for empty or whitespace name", () => {
      const dataUri = generateInitialsAvatar("   ");
      const decoded = decodeURIComponent(dataUri);
      assert.ok(decoded.includes("U"));
    });

    it("should generate valid SVG markup with requested dimensions", () => {
      const dataUri = generateInitialsAvatar("Code Master", 128);
      const decoded = decodeURIComponent(dataUri);
      assert.ok(decoded.includes('width="128"'));
      assert.ok(decoded.includes('height="128"'));
      assert.ok(decoded.includes('viewBox="0 0 128 128"'));
    });
  });

  describe("validateAvatarFile constraints and limits", () => {
    it("should reject null or undefined file input", async () => {
      const result = await validateAvatarFile(null as any);
      assert.equal(result.valid, false);
      assert.ok(result.error?.includes("No file"));
    });

    it("should reject empty (0-byte) files", async () => {
      const emptyFile = new File([], "avatar.jpg", { type: "image/jpeg" });
      const result = await validateAvatarFile(emptyFile);
      assert.equal(result.valid, false);
      assert.ok(result.error?.includes("empty"));
    });

    it("should reject files exceeding the 5MB limit", async () => {
      // Mock an oversized 6MB file
      const largeBlob = new Blob([new Uint8Array(6 * 1024 * 1024)], { type: "image/jpeg" });
      const largeFile = new File([largeBlob], "huge-photo.jpg", { type: "image/jpeg" });
      const result = await validateAvatarFile(largeFile);
      assert.equal(result.valid, false);
      assert.ok(result.error?.includes("exceeds the 5 MB limit"));
    });

    it("should reject forbidden file extensions (e.g., .svg, .exe, .html)", async () => {
      const badExtFile = new File([new Uint8Array([0xff, 0xd8, 0xff])], "malicious.svg", {
        type: "image/svg+xml",
      });
      const result = await validateAvatarFile(badExtFile);
      assert.equal(result.valid, false);
      assert.ok(result.error?.includes("Unsupported file extension"));
    });

    it("should reject forbidden MIME types", async () => {
      const badMimeFile = new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], "avatar.jpg", {
        type: "application/x-executable",
      });
      const result = await validateAvatarFile(badMimeFile);
      assert.equal(result.valid, false);
      assert.ok(result.error?.includes("Unsupported MIME type"));
    });

    it("should reject extension spoofing when content is text but renamed to .png", async () => {
      const spoofedFile = new File([new TextEncoder().encode("<html>evil payload</html>")], "fake.png", {
        type: "image/png",
      });
      const result = await validateAvatarFile(spoofedFile);
      assert.equal(result.valid, false);
      assert.ok(result.error?.includes("spoofed"));
    });
  });

  describe("Constants consistency", () => {
    it("should define MAX_AVATAR_BYTES as 5MB matching backend", () => {
      assert.equal(MAX_AVATAR_BYTES, 5 * 1024 * 1024);
    });

    it("should enforce bounds 16px to 4096px", () => {
      assert.equal(MIN_AVATAR_DIMENSION, 16);
      assert.equal(MAX_AVATAR_DIMENSION, 4096);
    });

    it("should include all 4 supported web image formats", () => {
      assert.deepEqual(
        ALLOWED_AVATAR_EXTENSIONS as unknown as string[],
        [".jpg", ".jpeg", ".png", ".webp", ".gif"]
      );
      assert.deepEqual(
        ALLOWED_AVATAR_MIME_TYPES as unknown as string[],
        ["image/jpeg", "image/png", "image/webp", "image/gif"]
      );
    });
  });
});
