/**
 * @source i7n-ui/src/design-system/ui/card.tsx
 * @deps @/lib/utils
 * @tracking-component shadcn-card
 * Subcomponents (CardHeader, CardFooter, ...) are composed inside a tracked Card root and do not require trackingId.
 */
import * as React from "react";
import { cn } from "@/lib/utils";

export type CardProps = React.ComponentProps<"div"> & {
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
};

const Card = React.forwardRef<HTMLDivElement, CardProps>(function Card({ className, trackingId, ...props }, ref) {
  return (
    <div
      ref={ref}
      data-slot="card"
      data-i7n-component="shadcn-card"
      data-i7n-name={trackingId}
      className={cn("flex flex-col", className)}
      {...props}
    />
  );
});

Card.displayName = "Card";

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-header" className={cn("grid gap-2", className)} {...props} />;
}

function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-title" className={cn("font-semibold leading-none", className)} {...props} />;
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-description" className={cn("text-sm", className)} {...props} />;
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-action" className={cn("justify-self-end", className)} {...props} />;
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-content" className={cn(className)} {...props} />;
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-footer" className={cn("flex items-center", className)} {...props} />;
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
};
