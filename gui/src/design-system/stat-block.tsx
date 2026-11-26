/**
 * @source i7n-ui/src/design-system/stat-block.tsx
 * @deps @/lib/utils, ./card
 * @tracking-component stat-block
 */
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Card } from "./card";

export interface StatBlockProps extends HTMLAttributes<HTMLDivElement> {
  value: ReactNode;
  source?: ReactNode;
  layout?: "row" | "stacked";
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

export function StatBlock({ value, source, layout = "row", children, className, trackingId, ...props }: StatBlockProps) {
  return (
    <Card
      className={cn("ds-stat", className)}
      data-i7n-component="stat-block"
      data-i7n-name={trackingId}
      data-layout={layout}
      trackingId={trackingId}
      {...props}
    >
      <strong className="ds-stat-value">{value}</strong>
      <div>{children}{source && <span className="ds-stat-source">{source}</span>}</div>
    </Card>
  );
}
