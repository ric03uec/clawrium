"use client";

import { useRouter } from "next/navigation";
import { type TopologyAgent } from "@/lib/types";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/ui/status-dot";

interface AgentInfoModalProps {
  agent: TopologyAgent | null;
  hostAlias: string;
  onClose: () => void;
}

export function AgentInfoModal({ agent, hostAlias, onClose }: AgentInfoModalProps) {
  const router = useRouter();

  if (!agent) return null;

  const fields = [
    { label: "Status", value: agent.status, isStatus: true },
    { label: "Type", value: agent.agent_type },
    { label: "Host", value: hostAlias },
    { label: "Model", value: agent.model || "—" },
    { label: "Version", value: agent.version || "—" },
    { label: "Uptime", value: agent.uptime || "—" },
    { label: "Provider", value: agent.provider || "—" },
    { label: "Provider Type", value: agent.provider_type || "—" },
    ...(agent.provider_endpoint
      ? [{ label: "Provider Endpoint", value: agent.provider_endpoint }]
      : []),
  ];

  return (
    <Modal
      open={!!agent}
      onClose={onClose}
      title={agent.agent_name}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              router.push(
                `/agents?key=${encodeURIComponent(agent.agent_key)}`
              );
            }}
          >
            View Details →
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {fields.map(({ label, value, isStatus }) => (
          <div key={label} className="flex items-center justify-between">
            <span className="text-xs text-muted">{label}</span>
            {isStatus ? (
              <span className="flex items-center gap-1.5">
                <StatusDot status={agent.status} size="sm" />
                <span className="text-xs font-medium text-primary-text capitalize">
                  {agent.status.replace(/_/g, " ")}
                </span>
              </span>
            ) : (
              <span
                className="text-xs font-medium text-primary-text truncate max-w-[220px]"
                title={typeof value === "string" ? value : undefined}
              >
                {value}
              </span>
            )}
          </div>
        ))}
      </div>
    </Modal>
  );
}
