/**
 * @source i7n-ui/src/design-system/card.tsx
 * @deps @/lib/utils, @/design-system/ui/card
 * @tracking-component card
 */
import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import { Card as ShadcnCard } from "./ui/card";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "flat" | "plain" | "raised" | "gradient" | "glow";
  padding?: "sm" | "md" | "lg";
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

/**
 * Clawrium adaptation: forwards refs and retains the legacy padding choices.
 * Padding is expressed as data so the copied stylesheet remains authoritative.
 */
export const Card = forwardRef<HTMLDivElement, CardProps>(function Card({
  variant = "flat",
  padding = "md",
  className,
  trackingId,
  ...props
}, ref) {
  return (
    <ShadcnCard
      ref={ref}
      className={cn("ds-card gap-0", className)}
      data-i7n-component="card"
      data-i7n-name={trackingId}
      data-variant={variant}
      data-padding={padding}
      trackingId={trackingId}
      {...props}
    />
  );
});

Card.displayName = "Card";
