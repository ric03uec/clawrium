/**
 * @source i7n-ui/src/design-system/page-header.tsx
 * @deps @/lib/utils, ./eyebrow
 * @tracking-component page-header
 */
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Eyebrow } from "./eyebrow";

export interface PageHeaderProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  eyebrow: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

export function PageHeader({ eyebrow, title, description, actions, className, trackingId, ...props }: PageHeaderProps) {
  return (
    <header
      className={cn("ds-page-header", className)}
      data-i7n-component="page-header"
      data-i7n-name={trackingId}
      {...props}
    >
      <div className="ds-page-header-main">
        <Eyebrow trackingId={`${trackingId}.eyebrow`}>{eyebrow}</Eyebrow>
        <div className="ds-page-title-row">
          <h1>{title}</h1>
          {description && <p>{description}</p>}
        </div>
      </div>
      {actions && <div className="ds-page-actions">{actions}</div>}
    </header>
  );
}
