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

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface rounded-lg px-3 py-2">
      <div className="text-[10px] text-muted uppercase tracking-wide mb-0.5">
        {label}
      </div>
      <div
        className="text-xs font-medium text-primary-text truncate"
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

export function AgentInfoModal({ agent, hostAlias, onClose }: AgentInfoModalProps) {
  const router = useRouter();

  if (!agent) return null;

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
            View Details &rarr;
          </Button>
        </>
      }
    >
      {/* Status header */}
      <div className="flex items-center gap-2 mb-3 pb-3 border-b border-subtle">
        <StatusDot status={agent.status} size="md" />
        <span className="text-sm font-medium text-primary-text capitalize">
          {agent.status.replace(/_/g, " ")}
        </span>
      </div>

      {/* Compact card grid */}
      <div className="grid grid-cols-2 gap-2">
        <InfoCard label="Type" value={agent.agent_type} />
        <InfoCard label="Host" value={hostAlias} />
        <InfoCard label="Model" value={agent.model || "\u2014"} />
        <InfoCard label="Version" value={agent.version || "\u2014"} />
        <InfoCard label="Uptime" value={agent.uptime || "\u2014"} />
        <InfoCard label="Provider" value={agent.provider || "\u2014"} />
        {agent.provider_type && (
          <InfoCard label="Provider Type" value={agent.provider_type} />
        )}
        {agent.provider_endpoint && (
          <InfoCard label="Endpoint" value={agent.provider_endpoint} />
        )}
      </div>
    </Modal>
  );
}
