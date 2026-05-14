"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

interface ControlNodeData {
  label: string;
  description: string;
}

export function ControlNode({ data }: NodeProps) {
  const { label, description } = data as unknown as ControlNodeData;

  return (
    <div className="bg-white border-2 border-primary rounded-xl px-6 py-4 shadow-md min-w-[180px] text-center">
      <div className="text-xs font-medium text-primary uppercase tracking-wide mb-1">
        {description}
      </div>
      <div className="text-sm font-semibold text-primary-text">{label}</div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-primary !w-2 !h-2 !border-0"
      />
    </div>
  );
}
