"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { type AgentStatus, type TopologyAgent } from "@/lib/types";
import { StatusDot } from "@/components/ui/status-dot";

interface HostNodeData {
  hostname: string;
  alias: string;
  user: string;
  agentCount: number;
  agents: TopologyAgent[];
  onAgentClick: (agent: TopologyAgent) => void;
  onHostClick: (hostname: string) => void;
}

export function HostNode({ data }: NodeProps) {
  const { hostname, alias, user, agents, onAgentClick, onHostClick } =
    data as unknown as HostNodeData;

  return (
    <div className="bg-white border border-default rounded-xl shadow-sm min-w-[220px]">
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-primary !w-2 !h-2 !border-0"
      />

      {/* Host header */}
      <button
        onClick={() => onHostClick(hostname)}
        className="w-full px-4 py-3 border-b border-default text-left hover:bg-surface transition-colors rounded-t-xl"
      >
        <div className="text-sm font-semibold text-primary-text">{alias}</div>
        <div className="text-xs text-muted">
          {user}@{hostname}
        </div>
      </button>

      {/* Agent cards */}
      <div className="p-2 space-y-1">
        {agents.length === 0 ? (
          <div className="text-xs text-muted text-center py-2">No agents</div>
        ) : (
          agents.map((agent) => (
            <div key={agent.agent_key} className="relative">
              <button
                onClick={() => onAgentClick(agent)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-surface transition-colors text-left"
              >
                <StatusDot status={agent.status as AgentStatus} size="sm" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-primary-text truncate">
                    {agent.agent_name}
                  </div>
                  <div className="text-[10px] text-muted truncate">
                    {agent.agent_type} &middot; {agent.model || "no model"}
                  </div>
                </div>
              </button>
              <Handle
                type="source"
                position={Position.Bottom}
                id={agent.agent_key}
                className="!bg-slate-400 !w-1.5 !h-1.5 !border-0 !left-1/2 !-translate-x-1/2"
              />
            </div>
          ))
        )}
      </div>
    </div>
  );
}
