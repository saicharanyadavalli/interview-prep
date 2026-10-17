/**
 * Avatar validation and client-side image processing utility.
 *
 * Enforces strict security constraints:
 * - File size <= 5 MB
 * - Allowed formats: JPEG, PNG, WebP, GIF
 * - Header magic-byte verification against content spoofing
 * - Dimension bounds: 16px <= width, height <= 4096px
 * - Memory leak prevention through deterministic URL.revokeObjectURL
 */

export const MAX_AVATAR_BYTES = 5 * 1024 * 1024; // 5 MB
export const MIN_AVATAR_DIMENSION = 16;
export const MAX_AVATAR_DIMENSION = 4096;

export const ALLOWED_AVATAR_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
] as const;

export const ALLOWED_AVATAR_EXTENSIONS = [
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".gif",
] as const;

export interface ValidationResult {
  valid: boolean;
  error?: string;
  width?: number;
  height?: number;
  format?: string;
  detectedMime?: string;
}

/**
 * Inspect magic bytes of the first slice of the file buffer to prevent extension spoofing.
 */
export function detectImageMagicBytes(buffer: ArrayBuffer): {
  valid: boolean;
  format?: string;
  mime?: string;
} {
  const bytes = new Uint8Array(buffer);
  if (bytes.length < 4) {
    return { valid: false };
  }

  // JPEG: FF D8 FF
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return { valid: true, format: "jpeg", mime: "image/jpeg" };
  }

  // PNG: 89 50 4E 47 0D 0A 1A 0A
  if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  ) {
    return { valid: true, format: "png", mime: "image/png" };
  }

  // GIF: 47 49 46 38 ('GIF87a' or 'GIF89a')
  if (
    bytes[0] === 0x47 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x38
  ) {
    return { valid: true, format: "gif", mime: "image/gif" };
  }

  // WebP: RIFF (bytes 0-3) and WEBP (bytes 8-11)
  if (
    bytes.length >= 12 &&
    bytes[0] === 0x52 && // R
    bytes[1] === 0x49 && // I
    bytes[2] === 0x46 && // F
    bytes[3] === 0x46 && // F
    bytes[8] === 0x57 && // W
    bytes[9] === 0x45 && // E
    bytes[10] === 0x42 && // B
    bytes[11] === 0x50 // P
  ) {
    return { valid: true, format: "webp", mime: "image/webp" };
  }

  return { valid: false };
}

/**
 * Safely measures image dimensions in the browser, revoking the object URL deterministically.
 */
export function measureImageDimensions(
  file: File
): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") {
      resolve({ width: 0, height: 0 });
      return;
    }

    let objectUrl = "";
    try {
      objectUrl = URL.createObjectURL(file);
    } catch (err: any) {
      reject(new Error("Failed to create image object URL: " + err.message));
      return;
    }

    const img = new window.Image();
    let cleanedUp = false;

    const cleanup = () => {
      if (!cleanedUp) {
        cleanedUp = true;
        try {
          URL.revokeObjectURL(objectUrl);
        } catch (_) {}
      }
    };

    img.onload = () => {
      const width = img.naturalWidth || img.width;
      const height = img.naturalHeight || img.height;
      cleanup();
      resolve({ width, height });
    };

    img.onerror = () => {
      cleanup();
      reject(new Error("The image appears corrupt or could not be decoded."));
    };

    img.src = objectUrl;
  });
}

/**
 * Validate avatar file against size, MIME, magic bytes, extension, and dimensions.
 */
export async function validateAvatarFile(file: File): Promise<ValidationResult> {
  if (!file) {
    return { valid: false, error: "No file was selected." };
  }

  // 1. File size check
  if (file.size <= 0) {
    return { valid: false, error: "The selected file is empty." };
  }
  if (file.size > MAX_AVATAR_BYTES) {
    const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
    return {
      valid: false,
      error: `File size (${sizeMb} MB) exceeds the 5 MB limit. Please choose a smaller image.`,
    };
  }

  // 2. Extension check
  const fileName = (file.name || "").toLowerCase();
  const hasValidExt = ALLOWED_AVATAR_EXTENSIONS.some((ext) =>
    fileName.endsWith(ext)
  );
  if (!hasValidExt) {
    return {
      valid: false,
      error: "Unsupported file extension. Allowed formats: JPG, PNG, WebP, GIF.",
    };
  }

  // 3. MIME type check
  const normalizedMime = (file.type || "").toLowerCase();
  const isAllowedMime = (ALLOWED_AVATAR_MIME_TYPES as readonly string[]).includes(
    normalizedMime
  );
  if (!isAllowedMime && normalizedMime !== "") {
    return {
      valid: false,
      error: `Unsupported MIME type '${file.type}'. Allowed: JPEG, PNG, WebP, GIF.`,
    };
  }

  // 4. Magic bytes validation
  try {
    const headerBuffer = await file.slice(0, 16).arrayBuffer();
    const magic = detectImageMagicBytes(headerBuffer);
    if (!magic.valid) {
      return {
        valid: false,
        error:
          "Invalid or spoofed image file header. Please upload a genuine JPEG, PNG, WebP, or GIF image.",
      };
    }

    // 5. Dimension bounds check
    const { width, height } = await measureImageDimensions(file);
    if (width < MIN_AVATAR_DIMENSION || height < MIN_AVATAR_DIMENSION) {
      return {
        valid: false,
        error: `Image dimensions (${width}x${height}px) are too small. Minimum size is ${MIN_AVATAR_DIMENSION}x${MIN_AVATAR_DIMENSION}px.`,
        width,
        height,
      };
    }
    if (width > MAX_AVATAR_DIMENSION || height > MAX_AVATAR_DIMENSION) {
      return {
        valid: false,
        error: `Image dimensions (${width}x${height}px) exceed the maximum permitted (${MAX_AVATAR_DIMENSION}x${MAX_AVATAR_DIMENSION}px).`,
        width,
        height,
      };
    }

    return {
      valid: true,
      width,
      height,
      format: magic.format,
      detectedMime: magic.mime,
    };
  } catch (err: any) {
    return {
      valid: false,
      error: err.message || "Failed to validate image.",
    };
  }
}

/**
 * Optimizes an avatar by drawing it to an off-screen canvas and scaling down to max 1024px
 * while preserving aspect ratio. Outputs JPEG/WebP to save bandwidth.
 */
export async function optimizeAvatarImage(
  file: File,
  maxDimension = 1024,
  quality = 0.88
): Promise<File> {
  // If already under 300KB and within maxDimension, no downscaling needed
  if (file.size <= 300 * 1024) {
    return file;
  }

  if (typeof window === "undefined" || typeof document === "undefined") {
    return file;
  }

  const { width, height } = await measureImageDimensions(file);
  if (width === 0 || height === 0) return file;

  let targetW = width;
  let targetH = height;

  if (Math.max(targetW, targetH) > maxDimension) {
    const ratio = maxDimension / Math.max(targetW, targetH);
    targetW = Math.max(1, Math.round(targetW * ratio));
    targetH = Math.max(1, Math.round(targetH * ratio));
  }

  const canvas = document.createElement("canvas");
  canvas.width = targetW;
  canvas.height = targetH;

  const ctx = canvas.getContext("2d");
  if (!ctx) return file;

  const objectUrl = URL.createObjectURL(file);
  try {
    const img = new window.Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("Failed to load image for optimization."));
      img.src = objectUrl;
    });

    ctx.drawImage(img, 0, 0, targetW, targetH);

    const blob: Blob | null = await new Promise((resolve) =>
      canvas.toBlob((b) => resolve(b), "image/jpeg", quality)
    );

    if (blob && blob.size < file.size) {
      const baseName = (file.name || "avatar").replace(/\.[^.]+$/, "");
      return new File([blob], `${baseName}.jpg`, {
        type: "image/jpeg",
        lastModified: Date.now(),
      });
    }

    return file;
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

/**
 * Generates an accessible, clean SVG data URI avatar with user initials.
 */
export function generateInitialsAvatar(nameOrUser?: string | null, size = 96): string {
  const text = String(nameOrUser || "").trim();
  let initials = "U";

  if (text) {
    const parts = text.split(/[\s_\-]+/).filter(Boolean);
    if (parts.length >= 2) {
      initials = (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    } else if (parts[0]) {
      initials = parts[0].slice(0, 2).toUpperCase();
    }
  }

  // Consistent pleasant background color palette based on name hash
  const colors = [
    "#0f766e", // teal
    "#1d4ed8", // blue
    "#7c3aed", // violet
    "#c026d3", // fuchsia
    "#d97706", // amber
    "#059669", // emerald
    "#4338ca", // indigo
  ];
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = (hash << 5) - hash + text.charCodeAt(i);
    hash |= 0;
  }
  const color = colors[Math.abs(hash) % colors.length];

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <rect width="${size}" height="${size}" rx="${Math.floor(size / 2)}" fill="${color}"/>
    <text x="50%" y="54%" text-anchor="middle" dominant-baseline="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" font-weight="600" font-size="${Math.floor(size * 0.42)}" fill="#ffffff">${initials}</text>
  </svg>`;

  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
