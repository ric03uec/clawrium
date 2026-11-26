import { StatusLight, type StatusLightTone } from "@/design-system";
import { type AgentStatus } from "@/lib/types";

export interface AgentStatusPresentation {
  label: string;
  tone: StatusLightTone;
  color: string;
  pulse: boolean;
}

export const AGENT_STATUS_PRESENTATION: Record<AgentStatus, AgentStatusPresentation> = {
  running: { label: "Running", tone: "green", color: "#22c55e", pulse: true },
  stopped: { label: "Stopped", tone: "red", color: "var(--destructive)", pulse: false },
  degraded: { label: "Degraded", tone: "yellow", color: "#e9a23b", pulse: false },
  not_installed: { label: "Not Installed", tone: "yellow", color: "#e9a23b", pulse: false },
  pending_onboard: { label: "Pending", tone: "yellow", color: "#e9a23b", pulse: false },
  onboarding: { label: "Onboarding", tone: "blue", color: "var(--blue-500)", pulse: false },
  ready: { label: "Ready", tone: "blue", color: "var(--blue-500)", pulse: false },
  checking: { label: "Checking", tone: "gray", color: "#a3a3a3", pulse: true },
  install_missing: { label: "Install Missing", tone: "red", color: "var(--destructive)", pulse: false },
  unknown: { label: "Unknown", tone: "gray", color: "#a3a3a3", pulse: false },
};

interface StatusDotProps {
  status: AgentStatus;
  size?: "sm" | "md" | "lg";
  trackingId?: string;
}

/**
 * Compact compatibility wrapper for topology nodes and the three raw tables.
 * New ordinary status labels should use StatusChip; this wrapper centralizes
 * AgentStatus mapping while retaining existing dot sizes and pulse semantics.
 */
export function StatusDot({ status, size = "sm", trackingId }: StatusDotProps) {
  const presentation = AGENT_STATUS_PRESENTATION[status];
  const sizeClass = size === "lg" ? "!h-4 !w-4" : size === "md" ? "!h-3 !w-3" : "!h-2 !w-2";

  return (
    <StatusLight
      trackingId={trackingId ?? `compat.status-dot.${status.replaceAll("_", "-")}`}
      tone={presentation.tone}
      className={`${sizeClass}${presentation.pulse ? " animate-pulse" : ""}`}
      title={status}
      data-status={status}
    />
  );
}
