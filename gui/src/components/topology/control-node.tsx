"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

interface ControlNodeData {
  label: string;
  description: string;
}

export function ControlNode({ data }: NodeProps) {
  const { label, description } = data as unknown as ControlNodeData;

  return (
    <div className="flex flex-col items-center gap-0.5 px-4 py-2 opacity-60">
      <Handle
        type="source"
        position={Position.Top}
        className="!bg-muted !w-1.5 !h-1.5 !border-0"
      />
      <div className="text-[10px] text-muted uppercase tracking-widest">
        {description}
      </div>
      <div className="text-xs font-medium text-secondary">{label}</div>
    </div>
  );
}
