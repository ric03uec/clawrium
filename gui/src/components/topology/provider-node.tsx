"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { type ProviderNodeData } from "./topology-graph";
import {
  getProviderBrand,
  isNvidiaLocalInference,
  NVIDIA_BRAND,
} from "./provider-brands";

export function ProviderNode({ data }: NodeProps) {
  const { name, type, endpoint, agentCount, unconfigured, hostGpuVendor } =
    data as unknown as ProviderNodeData & { hostGpuVendor?: string | null };

  const isNvidia = isNvidiaLocalInference(type, hostGpuVendor);
  const brand = isNvidia ? NVIDIA_BRAND : getProviderBrand(type);
  const { label, Icon, accentColor } = brand;

  const borderStyle = unconfigured
    ? { borderLeft: "2px dashed var(--border-default)" }
    : { borderLeft: `3px solid ${accentColor}` };

  return (
    <div
      className={`bg-white rounded-lg shadow-sm min-w-[140px] max-w-[180px] px-3 py-2.5 border border-default`}
      style={{
        ...borderStyle,
        borderTop: "1px solid var(--border-default)",
        borderRight: "1px solid var(--border-default)",
        borderBottom: "1px solid var(--border-default)",
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className={
          unconfigured
            ? "!bg-muted !w-1.5 !h-1.5 !border-0"
            : "!bg-slate-400 !w-1.5 !h-1.5 !border-0"
        }
      />

      {/* Logo + label row */}
      <div className="flex items-center gap-2 mb-1">
        <Icon
          className={isNvidia ? "h-5 w-5" : "h-4 w-4"}
          title={label}
        />
        <span
          className={`text-[11px] font-semibold truncate ${
            unconfigured ? "text-muted" : "text-primary-text"
          }`}
        >
          {isNvidia ? "NVIDIA · Local" : label}
        </span>
      </div>

      {/* Provider name */}
      <div
        className="text-[10px] text-secondary font-medium truncate"
        title={name}
      >
        {name}
      </div>

      {/* Endpoint (if present) */}
      {endpoint && (
        <div
          className="text-[9px] text-muted truncate mt-0.5"
          title={endpoint}
        >
          {endpoint}
        </div>
      )}

      {/* Agent count */}
      {!unconfigured && (
        <div className="text-[9px] text-muted mt-1">
          {agentCount} {agentCount === 1 ? "agent" : "agents"}
        </div>
      )}
    </div>
  );
}
