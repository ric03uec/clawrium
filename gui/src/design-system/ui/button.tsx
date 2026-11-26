/**
 * @source i7n-ui/src/design-system/ui/button.tsx
 * @deps @/lib/utils
 * @tracking-component shadcn-button
 */
import * as React from "react";
import { cn } from "@/lib/utils";

export type ButtonProps = React.ComponentProps<"button"> & {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "xs" | "sm" | "lg" | "icon" | "icon-xs" | "icon-sm" | "icon-lg";
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
};

/**
 * Tailwind 3 adaptation: the copied public Button does not expose `asChild`, so
 * the upstream Radix Slot and class-variance-authority layer are unnecessary.
 * Presentation is owned by the stable `.ds-button` selectors in styles.css.
 */
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button({
  className,
  variant = "default",
  size = "default",
  trackingId,
  ...props
}, ref) {
  return (
    <button
      ref={ref}
      data-slot="button"
      data-i7n-component="shadcn-button"
      data-i7n-name={trackingId}
      data-variant={variant}
      data-size={size}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap disabled:pointer-events-none disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
});

Button.displayName = "Button";

export { Button };
