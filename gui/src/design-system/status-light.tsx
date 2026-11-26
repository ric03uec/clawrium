/**
 * @source i7n-ui/src/design-system/status-light.tsx
 * @deps @/lib/utils
 * @tracking-component status-light
 */
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export type StatusLightTone = "green" | "yellow" | "red" | "blue" | "gray";

export interface StatusLightProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: StatusLightTone;
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

export function StatusLight({ tone = "gray", className, trackingId, ...props }: StatusLightProps) {
  return (
    <span
      className={cn("ds-status-light", className)}
      data-i7n-component="status-light"
      data-i7n-name={trackingId}
      data-light={tone}
      {...props}
    />
  );
}
