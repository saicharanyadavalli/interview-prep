"use client";

import React, { useState, useEffect } from "react";
import Image from "next/image";
import { generateInitialsAvatar } from "@/utils/avatar-validation";

export interface UserAvatarProps {
  src?: string | null;
  name?: string | null;
  username?: string | null;
  size?: number;
  className?: string;
  alt?: string;
  priority?: boolean;
  style?: React.CSSProperties;
}

/**
 * Robust UserAvatar component with:
 * - Deterministic fallback to initials SVG if avatarUrl is missing, empty, or fails to load
 * - Prevention of broken image icons, infinite error loops, and flicker
 * - Support for data: URLs, Cloudinary URLs, and remote URLs via unoptimized flag
 * - Auto-reset of error state when src changes
 */
export function UserAvatar({
  src,
  name,
  username,
  size = 32,
  className = "",
  alt,
  priority = false,
  style,
}: UserAvatarProps) {
  const [hasError, setHasError] = useState(false);

  // Reset error state whenever the image source changes
  useEffect(() => {
    setHasError(false);
  }, [src]);

  const displayName = name || username || "User";
  const fallbackSrc = generateInitialsAvatar(name || username, size);
  const effectiveSrc = (!hasError && src && src.trim().length > 0) ? src.trim() : fallbackSrc;

  // Next.js Image optimizer doesn't handle data: URIs or unconfigured remote domains
  const isDataUri = effectiveSrc.startsWith("data:");
  const isUnoptimized = isDataUri || effectiveSrc.startsWith("http://") || effectiveSrc.startsWith("https://");

  return (
    <Image
      className={className}
      src={effectiveSrc}
      alt={alt || `${displayName}'s avatar`}
      width={size}
      height={size}
      unoptimized={isUnoptimized}
      priority={priority}
      onError={() => {
        if (!hasError) {
          setHasError(true);
        }
      }}
      style={{
        borderRadius: "50%",
        objectFit: "cover",
        display: "inline-block",
        ...style,
      }}
    />
  );
}

export default UserAvatar;
