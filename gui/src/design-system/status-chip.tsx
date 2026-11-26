/**
 * @source i7n-ui/src/design-system/status-chip.tsx
 * @deps @/lib/utils
 * @tracking-component status-chip
 */
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface StatusChipProps extends HTMLAttributes<HTMLSpanElement> {
  status: string;
  label?: ReactNode;
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

export function StatusChip({ status, label, className, trackingId, ...props }: StatusChipProps) {
  return (
    <span
      className={cn("ds-status-chip", className)}
      data-i7n-component="status-chip"
      data-i7n-name={trackingId}
      data-status={status}
      {...props}
    >
      <span className="ds-status-dot" />
      {label ?? status}
    </span>
  );
}
