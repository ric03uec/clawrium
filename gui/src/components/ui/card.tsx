import { forwardRef } from "react";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  padding?: "sm" | "md" | "lg";
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ className = "", padding = "md", children, ...props }, ref) => {
    const paddingClass = {
      sm: "p-4",
      md: "p-6",
      lg: "p-8",
    }[padding];

    return (
      <div
        ref={ref}
        className={`bg-white rounded-xl border border-default shadow-sm ${paddingClass} ${className}`}
        {...props}
      >
        {children}
      </div>
    );
  }
);

Card.displayName = "Card";
