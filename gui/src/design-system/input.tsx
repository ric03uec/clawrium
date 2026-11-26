/**
 * @source i7n-ui/src/design-system/input.tsx
 * @deps @/lib/utils, @/design-system/ui/input
 * @tracking-component input
 */
import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import { Input as ShadcnInput } from "./ui/input";

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  size?: "lg" | "sm";
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

export function Input({ size = "lg", className, trackingId, ...props }: InputProps) {
  return (
    <ShadcnInput
      className={cn("ds-input", className)}
      data-i7n-component="input"
      data-i7n-name={trackingId}
      data-size={size}
      trackingId={trackingId}
      {...props}
    />
  );
}
