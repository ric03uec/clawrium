"use client";

import { type TopologyHost } from "@/lib/types";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/ui/status-dot";

interface HostInfoModalProps {
  host: TopologyHost | null;
  onClose: () => void;
}

export function HostInfoModal({ host, onClose }: HostInfoModalProps) {
  if (!host) return null;

  return (
    <Modal
      open={!!host}
      onClose={onClose}
      title={host.alias}
      footer={
        <Button variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
      }
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">Hostname</span>
          <span className="text-xs font-medium text-primary-text font-mono">
            {host.hostname}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">User</span>
          <span className="text-xs font-medium text-primary-text">
            {host.user}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">SSH Key</span>
          <span className="text-xs font-medium text-primary-text">
            {host.has_key ? "Configured" : "Not configured"}
          </span>
        </div>
        {host.addresses.length > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted">Addresses</span>
            <span className="text-xs font-medium text-primary-text font-mono">
              {host.addresses.map((a) => a.address).join(", ")}
            </span>
          </div>
        )}

        {/* Agent list */}
        <div className="pt-3 border-t border-default">
          <div className="text-xs font-medium text-muted mb-2">
            Agents ({host.agent_count})
          </div>
          {host.agents.length === 0 ? (
            <div className="text-xs text-muted">No agents installed</div>
          ) : (
            <div className="space-y-2">
              {host.agents.map((agent) => (
                <div
                  key={agent.agent_key}
                  className="flex items-center gap-2"
                >
                  <StatusDot status={agent.status} size="sm" />
                  <span className="text-xs text-primary-text">
                    {agent.agent_name}
                  </span>
                  <span className="text-[10px] text-muted ml-auto">
                    {agent.agent_type}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
