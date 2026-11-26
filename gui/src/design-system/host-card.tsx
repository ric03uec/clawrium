/**
 * @source i7n-ui/src/design-system/host-card.tsx
 * @deps @/lib/utils, lucide-react, ./status-light, ./agent-logo
 * @tracking-component host-card
 */
import type { ElementType, HTMLAttributes, ReactNode } from "react";
import { Server } from "lucide-react";
import { cn } from "@/lib/utils";
import { StatusLight, type StatusLightTone } from "./status-light";
import { AgentLogo } from "./agent-logo";

export interface HostCardAgent {
  id: string;
  name: string;
  kind: string;
  light: StatusLightTone;
  href?: string;
  title?: string;
}

export interface HostCardProps extends HTMLAttributes<HTMLDivElement> {
  name: string;
  kind: string;
  light?: StatusLightTone;
  href?: string;
  details?: { label: string; value: ReactNode }[];
  agents?: HostCardAgent[];
  maxVisibleAgents?: number;
  moreHref?: string;
  emptyMessage?: string;
  /** Pass next/link (or any anchor-compatible component) for client-side navigation. */
  linkAs?: ElementType;
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

export function HostCard({
  name,
  kind,
  light = "gray",
  href,
  details = [],
  agents = [],
  maxVisibleAgents = 5,
  moreHref,
  emptyMessage = "No agents on this host.",
  linkAs,
  className,
  trackingId,
  ...props
}: HostCardProps) {
  const L = (linkAs ?? "a") as ElementType;
  const visible = agents.slice(0, maxVisibleAgents);
  const overflow = agents.length - visible.length;
  return (
    <div
      className={cn("ds-host-card", className)}
      data-i7n-component="host-card"
      data-i7n-name={trackingId}
      {...props}
    >
      <div className="ds-host-card-head">
        <StatusLight trackingId={`${trackingId}.host-status`} tone={light} />
        <Server size={17} />
        {href
          ? <L className="ds-host-card-name" href={href}>{name}</L>
          : <span className="ds-host-card-name">{name}</span>}
        <span className="ds-host-card-kind">{kind}</span>
      </div>
      {details.length > 0 && (
        <dl className="ds-host-card-details">
          {details.map(({ label, value }) => (
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}
        </dl>
      )}
      {agents.length === 0
        ? <div className="ds-host-card-empty">{emptyMessage}</div>
        : (
          <div className="ds-host-card-agents">
            {visible.map((agent) => {
              const row = <>
                <StatusLight trackingId={`${trackingId}.agent.${agent.id}.status`} tone={agent.light} />
                <AgentLogo trackingId={`${trackingId}.agent.${agent.id}.logo`} kind={agent.kind} size={15} />
                <span>{agent.name}</span>
                <span className="ds-host-agent-kind">{agent.kind}</span>
              </>;
              return agent.href
                ? <L key={agent.id} className="ds-host-agent" href={agent.href} title={agent.title}>{row}</L>
                : <span key={agent.id} className="ds-host-agent" title={agent.title}>{row}</span>;
            })}
            {overflow > 0 && (moreHref
              ? <L className="ds-host-agent ds-host-agent-more" href={moreHref}>+{overflow} more</L>
              : <span className="ds-host-agent ds-host-agent-more">+{overflow} more</span>)}
          </div>
        )}
    </div>
  );
}
