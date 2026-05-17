"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  type AgentStatus,
  type HostHardware,
  type TopologyAgent,
} from "@/lib/types";
import { StatusDot } from "@/components/ui/status-dot";
import { NvidiaIcon } from "@/components/icons/nvidia";
import { AmdIcon } from "@/components/icons/amd";
import { IntelIcon } from "@/components/icons/intel";

interface HostNodeData {
  hostname: string;
  alias: string;
  user: string;
  agentCount: number;
  agents: TopologyAgent[];
  hardware?: HostHardware | null;
  onAgentClick?: (agent: TopologyAgent) => void;
  onHostClick?: (hostname: string) => void;
}

export const AGENT_COL_WIDTH = 160;
export const HOST_PADDING = 16;
export const HOST_MIN_WIDTH = AGENT_COL_WIDTH + HOST_PADDING * 2;

function ArchBadge({ arch }: { arch: string }) {
  return (
    <span className="inline-flex items-center rounded border border-default bg-surface px-1.5 py-0.5 text-[10px] font-medium text-secondary">
      {arch}
    </span>
  );
}

function GpuBadge({ vendor }: { vendor: string }) {
  const v = vendor.toLowerCase();
  if (v === "nvidia") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-default bg-surface px-1.5 py-0.5 text-[10px] font-medium text-primary-text">
        <NvidiaIcon className="h-3 w-3 text-[#76B900]" />
        NVIDIA
      </span>
    );
  }
  if (v === "amd") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-default bg-surface px-1.5 py-0.5 text-[10px] font-medium text-primary-text">
        <AmdIcon className="h-3 w-3 text-[#ED1C24]" />
        AMD
      </span>
    );
  }
  if (v === "intel") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-default bg-surface px-1.5 py-0.5 text-[10px] font-medium text-primary-text">
        <IntelIcon className="h-3 w-3 text-[#0071C5]" />
        Intel
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded border border-default bg-surface px-1.5 py-0.5 text-[10px] font-medium text-secondary">
      GPU
    </span>
  );
}

function HardwareBadges({ hardware }: { hardware: HostHardware }) {
  const arch = hardware.architecture;
  const gpu = hardware.gpu;
  const showArch = arch && arch.toLowerCase() !== "unknown";
  const showGpu = gpu?.present === true;
  if (!showArch && !showGpu) return null;
  return (
    <div className="flex items-center gap-1.5">
      {showArch ? <ArchBadge arch={arch as string} /> : null}
      {showGpu ? <GpuBadge vendor={gpu.vendor ?? "unknown"} /> : null}
    </div>
  );
}

export function HostNode({ data }: NodeProps) {
  const {
    hostname,
    alias,
    user,
    agents,
    hardware,
    onAgentClick,
    onHostClick,
  } = data as unknown as HostNodeData;

  const cols = Math.max(agents.length, 1);
  const width = cols * AGENT_COL_WIDTH + HOST_PADDING * 2;
  const hw = hardware ?? null;
  const productName = hw?.product_name ?? null;
  // Show product_name as a sub-line whenever we have it; covers the
  // NVIDIA "DGX Spark" case and any other system that exposes a useful
  // product name, regardless of vendor.
  const showProductSubLine = !!productName;

  return (
    <div
      className="bg-white border border-default rounded-xl shadow-sm"
      style={{ width, minWidth: HOST_MIN_WIDTH }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-primary !w-2 !h-2 !border-0"
      />

      {/* Agent columns row */}
      <div
        className="flex items-stretch gap-2"
        style={{ padding: HOST_PADDING }}
      >
        {agents.length === 0 ? (
          <div className="text-xs text-muted text-center py-4 w-full">
            No agents
          </div>
        ) : (
          agents.map((agent) => (
            <div
              key={agent.agent_key}
              className="relative flex flex-col"
              style={{ width: AGENT_COL_WIDTH - 8 }}
            >
              <button
                onClick={() => onAgentClick?.(agent)}
                className="flex flex-col items-start gap-1 px-3 py-2 rounded-lg border border-default bg-surface hover:bg-panel transition-colors text-left h-full"
              >
                <div className="flex items-center gap-1.5">
                  <StatusDot
                    status={agent.status as AgentStatus}
                    size="sm"
                  />
                  <div className="text-xs font-medium text-primary-text truncate">
                    {agent.agent_name}
                  </div>
                </div>
                <div className="text-[10px] text-muted truncate w-full">
                  {agent.agent_type}
                </div>
                <div className="text-[10px] text-muted truncate w-full">
                  {agent.model || "no model"}
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

      {/* Host strip (bottom) */}
      <button
        onClick={() => onHostClick?.(hostname)}
        className="w-full px-4 py-3 border-t border-default text-left hover:bg-surface transition-colors rounded-b-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-primary-text truncate">
              {alias}
            </div>
            <div className="text-xs text-muted truncate">
              {user}@{hostname}
            </div>
            {showProductSubLine ? (
              <div className="mt-0.5 text-[11px] text-secondary truncate">
                {productName}
              </div>
            ) : null}
          </div>
          {hw ? <HardwareBadges hardware={hw} /> : null}
        </div>
      </button>
    </div>
  );
}
