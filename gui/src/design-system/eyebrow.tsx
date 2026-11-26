/**
 * @source i7n-ui/src/design-system/eyebrow.tsx
 * @deps @/lib/utils
 * @tracking-component eyebrow
 */
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export interface EyebrowProps extends HTMLAttributes<HTMLDivElement> {
  number?: string | number;
  tone?: "primary" | "muted";
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

export function Eyebrow({ number, tone = "primary", children, className, trackingId, ...props }: EyebrowProps) {
  return (
    <div
      className={cn("ds-eyebrow", className)}
      data-i7n-component="eyebrow"
      data-i7n-name={trackingId}
      data-tone={tone}
      {...props}
    >
      {number != null && <span>{number} — </span>}{children}
    </div>
  );
}
