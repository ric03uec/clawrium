/**
 * @source i7n-ui/src/design-system/button.tsx
 * @deps @/lib/utils, @/design-system/ui/button
 * @tracking-component button
 */
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Button as ShadcnButton } from "./ui/button";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "solid" | "outline" | "secondary" | "ghost" | "pill" | "danger";
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  iconRight?: ReactNode;
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

/**
 * Clawrium adaptation: forwards refs and retains the legacy `danger` alias so
 * existing lifecycle/destructive controls can migrate without behavior loss.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({
  variant = "primary",
  size = "md",
  icon,
  iconRight,
  children,
  className,
  trackingId,
  ...props
}, ref) {
  const internalVariant = variant === "danger"
    ? "destructive"
    : variant === "primary" || variant === "solid" || variant === "pill"
      ? "default"
      : variant;

  return (
    <ShadcnButton
      ref={ref}
      variant={internalVariant}
      size={size === "md" ? "default" : size}
      className={cn("ds-button", className)}
      data-i7n-component="button"
      data-i7n-name={trackingId}
      data-variant={variant}
      data-size={size}
      trackingId={trackingId}
      {...props}
    >
      {icon}{children}{iconRight}
    </ShadcnButton>
  );
});

Button.displayName = "Button";
