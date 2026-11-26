import type { ReactNode } from "react";
import { Card } from "@/design-system";

interface ComingSoonProps {
  title?: string;
  description: ReactNode;
  actions?: ReactNode;
  trackingId: string;
}

export function ComingSoon({
  title = "Coming soon",
  description,
  actions,
  trackingId,
}: ComingSoonProps) {
  return (
    <Card trackingId={trackingId} padding="md" className="bg-panel">
      <h2 className="font-semibold">{title}</h2>
      <div className="mt-2 text-secondary">{description}</div>
      {actions ? <div className="mt-3">{actions}</div> : null}
    </Card>
  );
}
