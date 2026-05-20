"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { type AcceleratorVendor } from "@/lib/types";
import { type ProviderNodeData } from "./topology-graph";
import {
  getAcceleratorBadge,
  getProviderBrand,
} from "./provider-brands";

export function ProviderNode({ data }: NodeProps) {
  const {
    name,
    type,
    endpoint,
    agentCount,
    unconfigured,
    hostGpuVendor,
    acceleratorVendor,
  } = data as unknown as ProviderNodeData & {
    hostGpuVendor?: string | null;
    acceleratorVendor?: AcceleratorVendor | null;
  };

  const brand = getProviderBrand(type);
  const { label, Icon, accentColor } = brand;
  const accelerator = getAcceleratorBadge(type, acceleratorVendor, hostGpuVendor);

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
        <Icon className="h-4 w-4" title={label} />
        <span
          className={`text-[11px] font-semibold truncate ${
            unconfigured ? "text-muted" : "text-primary-text"
          }`}
        >
          {label}
        </span>
        {accelerator && (
          <span
            className="ml-auto inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-default text-[9px] font-semibold uppercase tracking-wide"
            style={{ color: accelerator.color }}
            title={`${accelerator.label} accelerator`}
          >
            <accelerator.Icon className="h-3 w-3" title={accelerator.label} />
            <span>{accelerator.label}</span>
          </span>
        )}
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
