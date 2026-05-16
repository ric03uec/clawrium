import { MarkerType, type Edge, type Node } from "@xyflow/react";

import { type TopologyAgent, type TopologyResponse } from "@/lib/types";

const HOST_ROW_Y = 180;
const PROVIDER_ROW_Y = 440;
const HOST_SPACING = 300;
const PROVIDER_SPACING = 260;
const UNCONFIGURED_KEY = "__unconfigured__";

export interface ProviderNodeData {
  providerKey: string;
  name: string;
  type: string | null;
  endpoint: string | null;
  agentCount: number;
  unconfigured: boolean;
}

export interface ComputeTopologyOptions {
  onAgentClick?: (agent: TopologyAgent, hostAlias: string) => void;
  onHostClick?: (hostname: string) => void;
}

interface ProviderAccumulator {
  key: string;
  name: string;
  type: string | null;
  endpoint: string | null;
  unconfigured: boolean;
  agents: Array<{ hostname: string; agentKey: string }>;
}

export function providerNodeKey(agent: TopologyAgent): string {
  if (!agent.provider && !agent.provider_type) return UNCONFIGURED_KEY;
  const type = agent.provider_type || "unknown";
  const name = agent.provider || type;
  const endpoint = agent.provider_endpoint ?? "";
  // encodeURIComponent escapes "|", so joining the URI-encoded segments with
  // "|" is unambiguous AND produces a key safe to embed in React Flow DOM IDs
  // (no quotes / brackets that could trip CSS attribute selectors).
  return [type, name, endpoint].map(encodeURIComponent).join("|");
}

export function computeTopology(
  data: TopologyResponse,
  opts: ComputeTopologyOptions = {}
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  nodes.push({
    id: "control",
    type: "control",
    position: { x: 0, y: 0 },
    data: { label: data.control.label, description: data.control.description },
  });

  const hostCount = data.hosts.length;
  const hostStartX = -((hostCount - 1) * HOST_SPACING) / 2;

  const providerOrder: string[] = [];
  const providerMap = new Map<string, ProviderAccumulator>();

  data.hosts.forEach((host, hostIndex) => {
    const hostNodeId = `host-${host.hostname}`;

    nodes.push({
      id: hostNodeId,
      type: "host",
      position: { x: hostStartX + hostIndex * HOST_SPACING, y: HOST_ROW_Y },
      data: {
        hostname: host.hostname,
        alias: host.alias,
        user: host.user,
        agentCount: host.agent_count,
        agents: host.agents,
        onAgentClick: opts.onAgentClick
          ? (agent: TopologyAgent) => opts.onAgentClick?.(agent, host.alias)
          : undefined,
        onHostClick: opts.onHostClick,
      },
    });

    edges.push({
      id: `edge-control-${host.hostname}`,
      source: "control",
      target: hostNodeId,
      type: "default",
      animated: true,
      style: { stroke: "#0D9488", strokeWidth: 1.5, strokeDasharray: "5 3" },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: "#0D9488",
        width: 16,
        height: 16,
      },
      label: "SSH",
      labelStyle: { fontSize: 10, fill: "#94A3B8" },
      labelBgStyle: { fill: "#FFFFFF", fillOpacity: 0.8 },
      labelBgPadding: [4, 2] as [number, number],
    });

    host.agents.forEach((agent) => {
      const pKey = providerNodeKey(agent);
      let acc = providerMap.get(pKey);
      if (!acc) {
        const unconfigured = pKey === UNCONFIGURED_KEY;
        acc = {
          key: pKey,
          name: unconfigured ? "Unconfigured" : agent.provider || agent.provider_type || "Unknown",
          type: unconfigured ? null : agent.provider_type ?? null,
          endpoint: unconfigured ? null : agent.provider_endpoint ?? null,
          unconfigured,
          agents: [],
        };
        providerMap.set(pKey, acc);
        providerOrder.push(pKey);
      }
      acc.agents.push({ hostname: host.hostname, agentKey: agent.agent_key });
    });
  });

  const providerCount = providerOrder.length;
  const providerStartX = -((providerCount - 1) * PROVIDER_SPACING) / 2;

  providerOrder.forEach((pKey, idx) => {
    const acc = providerMap.get(pKey)!;
    const providerNodeId = `provider-${pKey}`;
    nodes.push({
      id: providerNodeId,
      type: "provider",
      position: { x: providerStartX + idx * PROVIDER_SPACING, y: PROVIDER_ROW_Y },
      data: {
        providerKey: pKey,
        name: acc.name,
        type: acc.type,
        endpoint: acc.endpoint,
        agentCount: acc.agents.length,
        unconfigured: acc.unconfigured,
      } satisfies ProviderNodeData,
    });

    acc.agents.forEach(({ hostname, agentKey }) => {
      const stroke = acc.unconfigured ? "#94A3B8" : "#475569";
      edges.push({
        id: `edge-${hostname}-${agentKey}-${pKey}`,
        source: `host-${hostname}`,
        sourceHandle: agentKey,
        target: providerNodeId,
        type: "default",
        animated: false,
        style: {
          stroke,
          strokeWidth: 1.25,
          ...(acc.unconfigured ? { strokeDasharray: "4 3" } : {}),
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: stroke,
          width: 14,
          height: 14,
        },
      });
    });
  });

  return { nodes, edges };
}
