"use client";

import { useRouter } from "next/navigation";
import { Card } from "@/components/ui/card";
import { StatusDot } from "@/components/ui/status-dot";
import { useFleet, useFleetHealth } from "@/hooks";

export function AgentTable() {
  const { data: fleet, isLoading } = useFleet();
  // Start health polling — merges live status into fleet cache
  useFleetHealth();
  const router = useRouter();
  const agents = fleet?.agents ?? [];

  return (
    <Card padding="md" className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-secondary">Fleet Agents</h3>
        <span className="text-xs text-muted">
          {agents.length} agent{agents.length !== 1 ? "s" : ""}
        </span>
      </div>

      {isLoading ? (
        <div className="h-32 flex items-center justify-center text-muted text-sm">
          Loading...
        </div>
      ) : agents.length === 0 ? (
        <div className="h-32 flex items-center justify-center text-muted text-sm">
          No agents installed yet
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-default text-left">
                <th className="pb-3 pr-4 font-medium text-muted w-8"></th>
                <th className="pb-3 pr-4 font-medium text-muted">Name</th>
                <th className="pb-3 pr-4 font-medium text-muted">Type</th>
                <th className="pb-3 pr-4 font-medium text-muted">Host</th>
                <th className="pb-3 pr-4 font-medium text-muted">Model</th>
                <th className="pb-3 font-medium text-muted">Uptime</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr
                  key={agent.agent_key}
                  className="border-b border-default last:border-0 hover:bg-surface cursor-pointer transition-colors"
                  onClick={() =>
                    router.push(`/agents?key=${agent.agent_key}`)
                  }
                >
                  <td className="py-3 pr-4">
                    <StatusDot status={agent.status} size="md" />
                  </td>
                  <td className="py-3 pr-4 font-medium text-primary">
                    {agent.agent_name}
                  </td>
                  <td className="py-3 pr-4 text-secondary">
                    {agent.agent_type}
                  </td>
                  <td className="py-3 pr-4 text-secondary">
                    {agent.host_alias || agent.host}
                  </td>
                  <td className="py-3 pr-4 text-secondary font-mono text-xs">
                    {agent.model || "—"}
                  </td>
                  <td className="py-3 text-secondary">
                    {agent.uptime || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
