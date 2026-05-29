"use client";

/**
 * OS indicator for an agent's host. Renders icons served from
 * `/os-icons/` in the GUI public folder:
 *   gui/public/os-icons/macos.jpg   (used for os_family="darwin")
 *   gui/public/os-icons/linux.png   (used for os_family="linux")
 *
 * Missing-asset fallback: if the image fails to load (e.g. an environment
 * where the public files were stripped), the component hides the broken-
 * image glyph and renders just the text label.
 */

import { useState } from "react";
import type { OSFamily } from "@/lib/types";

interface OSStyle {
  src: string;
  label: string;
}

const STYLES: Record<OSFamily, OSStyle> = {
  darwin: { src: "/os-icons/macos.jpg", label: "macOS" },
  linux: { src: "/os-icons/linux.png", label: "Linux" },
};

export interface OSIconProps {
  os: OSFamily | null | undefined;
  /** Display variant:
   *   - `chip`: icon + text label (default; for tables/details)
   *   - `dot`:  icon only (for dense topology cards). Falls through to
   *             a small text monogram if the asset is missing.
   */
  variant?: "chip" | "dot";
  /** Pixel size for the icon (square). Defaults: 14 dot, 16 chip. */
  size?: number;
  className?: string;
}

export function OSIcon({
  os,
  variant = "chip",
  size,
  className = "",
}: OSIconProps) {
  const [imgFailed, setImgFailed] = useState(false);

  if (!os) return null;
  const style = STYLES[os];
  if (!style) return null;

  const dim = size ?? (variant === "dot" ? 14 : 16);

  const img = imgFailed ? null : (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={style.src}
      alt={style.label}
      width={dim}
      height={dim}
      onError={() => setImgFailed(true)}
      style={{
        width: dim,
        height: dim,
        objectFit: "contain",
        display: "inline-block",
      }}
    />
  );

  if (variant === "dot") {
    return (
      <span
        className={`inline-flex items-center leading-none ${className}`}
        title={style.label}
        aria-label={style.label}
      >
        {img ?? (
          <span className="text-[10px] font-semibold text-muted">
            {style.label.slice(0, 1).toUpperCase()}
          </span>
        )}
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${className}`}
      title={style.label}
      aria-label={style.label}
    >
      {img}
      <span>{style.label}</span>
    </span>
  );
}
