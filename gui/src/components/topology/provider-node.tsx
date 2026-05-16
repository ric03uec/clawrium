"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { type ProviderNodeData } from "./topology-graph";

const PROVIDER_LABELS: Record<string, string> = {
  ollama: "Ollama",
  openrouter: "OpenRouter",
  bedrock: "AWS Bedrock",
  anthropic: "Anthropic",
  openai: "OpenAI",
  opencode: "OpenCode",
};

const PROVIDER_GLYPHS: Record<string, string> = {
  ollama: "L",
  openrouter: "R",
  bedrock: "B",
  anthropic: "A",
  openai: "O",
  opencode: "C",
};

function providerLabel(type: string | null): string {
  if (!type) return "Provider";
  return PROVIDER_LABELS[type] ?? type;
}

function providerGlyph(type: string | null): string {
  if (!type) return "?";
  return PROVIDER_GLYPHS[type] ?? type.charAt(0).toUpperCase();
}

export function ProviderNode({ data }: NodeProps) {
  const { name, type, endpoint, agentCount, unconfigured } =
    data as unknown as ProviderNodeData;

  const borderClass = unconfigured
    ? "border-dashed border-default"
    : "border-primary/50";

  const labelClass = unconfigured ? "text-muted" : "text-primary";

  return (
    <div
      className={`bg-white rounded-xl shadow-sm min-w-[200px] px-4 py-3 border-2 ${borderClass}`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className={
          unconfigured
            ? "!bg-muted !w-2 !h-2 !border-0"
            : "!bg-primary !w-2 !h-2 !border-0"
        }
      />

      <div className="flex items-center gap-2 mb-1">
        <span
          className={`flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold ${
            unconfigured
              ? "bg-surface text-muted"
              : "bg-primary/10 text-primary"
          }`}
          aria-hidden="true"
        >
          {providerGlyph(type)}
        </span>
        <span
          className={`text-[10px] font-medium uppercase tracking-wide ${labelClass}`}
        >
          {providerLabel(type)}
        </span>
      </div>

      <div className="text-sm font-semibold text-primary-text truncate" title={name}>
        {name}
      </div>

      {endpoint && (
        <div
          className="text-[10px] text-muted truncate mt-0.5"
          title={endpoint}
        >
          {endpoint}
        </div>
      )}

      {!unconfigured && (
        <div className="text-[10px] text-muted mt-1">
          {agentCount} {agentCount === 1 ? "agent" : "agents"}
        </div>
      )}
    </div>
  );
}
