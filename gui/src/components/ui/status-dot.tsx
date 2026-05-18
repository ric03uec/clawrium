import { type AgentStatus } from "@/lib/types";

const STATUS_COLORS: Record<AgentStatus, string> = {
  running: "bg-status-running",
  stopped: "bg-status-error",
  degraded: "bg-status-warning",
  not_installed: "bg-status-warning",
  pending_onboard: "bg-status-warning",
  onboarding: "bg-status-info",
  ready: "bg-status-info",
  checking: "bg-gray-400",
  unknown: "bg-gray-400",
};

interface StatusDotProps {
  status: AgentStatus;
  size?: "sm" | "md" | "lg";
}

export function StatusDot({ status, size = "sm" }: StatusDotProps) {
  const sizeClass = size === "lg" ? "w-4 h-4" : size === "md" ? "w-3 h-3" : "w-2 h-2";
  const pulseClass = status === "running" || status === "checking" ? "animate-pulse" : "";

  return (
    <span
      className={`inline-block rounded-full ${sizeClass} ${STATUS_COLORS[status]} ${pulseClass}`}
      title={status}
    />
  );
}
