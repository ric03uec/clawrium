/**
 * @source i7n-ui/src/design-system/ui/input.tsx
 * @deps @/lib/utils
 * @tracking-component shadcn-input
 */
import * as React from "react";
import { cn } from "@/lib/utils";

export type InputProps = React.ComponentProps<"input"> & {
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
};

function Input({ className, type, trackingId, ...props }: InputProps) {
  return (
    <input
      type={type}
      data-slot="input"
      data-i7n-component="shadcn-input"
      data-i7n-name={trackingId}
      className={cn(
        "w-full min-w-0 bg-transparent outline-none disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
}

export { Input };
