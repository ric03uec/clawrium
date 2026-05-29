"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  type AgentStatus,
  type HostHardware,
  type OSFamily,
  type TopologyAgent,
} from "@/lib/types";
import { StatusDot } from "@/components/ui/status-dot";
import { OSIcon } from "@/components/ui/os-icon";
import { NvidiaIcon } from "@/components/icons/nvidia";
import { AmdIcon } from "@/components/icons/amd";
import { IntelIcon } from "@/components/icons/intel";

export interface AgentNodeData {
  agent: TopologyAgent;
  hostname: string;
  hostAlias: string;
  hardware: HostHardware | null;
  hostOsFamily: OSFamily | null;
  hostColor: string;
  onAgentClick?: (agent: TopologyAgent, hostAlias: string) => void;
  onHostClick?: (hostname: string) => void;
}

export const AGENT_NODE_WIDTH = 220;

function HardwareTag({ hardware }: { hardware: HostHardware }) {
  const arch = hardware.architecture;
  const gpu = hardware.gpu;
  const showArch = arch && arch.toLowerCase() !== "unknown";
  const showGpu = gpu?.present === true;
  if (!showArch && !showGpu) return null;

  const vendor = gpu?.vendor?.toLowerCase();

  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-muted">
      {showArch && <span>{arch}</span>}
      {showArch && showGpu && <span>·</span>}
      {showGpu && vendor === "nvidia" && (
        <span className="inline-flex items-center gap-0.5">
          <NvidiaIcon className="h-2.5 w-2.5 text-[#76B900]" />
          NVIDIA
        </span>
      )}
      {showGpu && vendor === "amd" && (
        <span className="inline-flex items-center gap-0.5">
          <AmdIcon className="h-2.5 w-2.5 text-[#ED1C24]" />
          AMD
        </span>
      )}
      {showGpu && vendor === "intel" && (
        <span className="inline-flex items-center gap-0.5">
          <IntelIcon className="h-2.5 w-2.5 text-[#0071C5]" />
          Intel
        </span>
      )}
      {showGpu && !["nvidia", "amd", "intel"].includes(vendor ?? "") && (
        <span>GPU</span>
      )}
    </span>
  );
}

export function AgentNode({ data }: NodeProps) {
  const {
    agent,
    hostname,
    hostAlias,
    hardware,
    hostOsFamily,
    hostColor,
    onAgentClick,
    onHostClick,
  } = data as unknown as AgentNodeData;

  return (
    <div
      className="bg-white rounded-xl shadow-md min-w-[220px] overflow-hidden"
      style={{
        width: AGENT_NODE_WIDTH,
        borderLeft: `3px solid ${hostColor}`,
        borderTop: "1px solid var(--border-default)",
        borderRight: "1px solid var(--border-default)",
        borderBottom: "1px solid var(--border-default)",
      }}
    >
      {/* Target handle for SSH edges from control */}
      <Handle
        type="target"
        position={Position.Bottom}
        id="ssh"
        style={{ left: "35%" }}
        className="!bg-muted !w-1.5 !h-1.5 !border-0"
      />

      {/* Agent info section (clickable) */}
      <button
        onClick={() => onAgentClick?.(agent, hostAlias)}
        className="relative w-full text-left px-4 py-3 hover:bg-surface/50 transition-colors"
      >
        <span className="absolute top-2 right-3 text-base" aria-hidden="true">🤖</span>
        {/* Name + status */}
        <div className="flex items-center gap-2 mb-2">
          <StatusDot status={agent.status as AgentStatus} size="md" />
          <span className="text-sm font-bold text-primary-text truncate">
            {agent.agent_name}
          </span>
        </div>

        {/* Info grid */}
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <span className="text-muted">Type</span>
          <span className="text-secondary font-medium truncate">
            {agent.agent_type}
          </span>
          <span className="text-muted">Model</span>
          <span className="text-secondary font-medium truncate">
            {agent.model || "—"}
          </span>
          <span className="text-muted">Provider</span>
          <span className="text-secondary font-medium truncate">
            {agent.provider || "—"}
          </span>
        </div>
      </button>

      {/* Host tag (bottom section) */}
      <button
        onClick={() => onHostClick?.(hostname)}
        className="w-full px-4 py-2 border-t border-subtle text-left hover:bg-surface/50 transition-colors"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: hostColor }}
            />
            <span className="text-[11px] font-medium text-secondary truncate">
              {hostAlias}
            </span>
            <OSIcon os={hostOsFamily} variant="dot" />
          </div>
          {hardware && <HardwareTag hardware={hardware} />}
        </div>
      </button>

      {/* Source handle for provider edges */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="provider"
        style={{ left: "65%" }}
        className="!bg-slate-400 !w-1.5 !h-1.5 !border-0"
      />
    </div>
  );
}
