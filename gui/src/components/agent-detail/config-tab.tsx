"use client";

import { AgentDetail } from "@/lib/types";
import { Card } from "@/components/ui/card";

interface ConfigTabProps {
  agent: AgentDetail;
}

export function ConfigTab({ agent }: ConfigTabProps) {
  return (
    <div className="space-y-6 p-4">
      <Card padding="md">
        <h3 className="text-sm font-semibold text-primary-text mb-4">Provider</h3>
        <div className="grid grid-cols-2 gap-y-3 text-sm">
          <InfoRow label="Name" value={agent.provider || "—"} />
          <InfoRow label="Type" value={agent.provider_type || "—"} />
          <InfoRow label="Model" value={agent.model || "—"} />
        </div>
      </Card>

      <Card padding="md">
        <h3 className="text-sm font-semibold text-primary-text mb-4">Gateway</h3>
        <div className="grid grid-cols-2 gap-y-3 text-sm">
          <InfoRow label="URL" value={agent.gateway_url || "—"} />
          <InfoRow
            label="Port"
            value={agent.gateway_port != null ? String(agent.gateway_port) : "—"}
          />
          <InfoRow label="Device ID" value={agent.device_id || "—"} />
        </div>
      </Card>

      <Card padding="md">
        <h3 className="text-sm font-semibold text-primary-text mb-4">Status</h3>
        <div className="grid grid-cols-2 gap-y-3 text-sm">
          <InfoRow label="Onboarding" value={agent.onboarding_step || "—"} />
          <InfoRow label="Version" value={agent.version || "—"} />
        </div>
      </Card>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span className="text-muted">{label}</span>
      <span className="text-primary-text font-mono text-xs truncate">{value}</span>
    </>
  );
}
