import { MarkerType, type Edge, type Node } from "@xyflow/react";

import { type TopologyAgent, type TopologyResponse } from "@/lib/types";
import {
  AGENT_COL_WIDTH,
  HOST_MIN_WIDTH,
  HOST_PADDING,
} from "./host-node";

const HOST_ROW_Y = 180;
const PROVIDER_ROW_Y = 480;
export const HOST_GAP = 48;
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
  agents: Array<{ hostname: string; agentKey: string; model: string | null }>;
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

function hostNodeWidth(agentCount: number): number {
  const cols = Math.max(agentCount, 1);
  return Math.max(cols * AGENT_COL_WIDTH + HOST_PADDING * 2, HOST_MIN_WIDTH);
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

  const providerOrder: string[] = [];
  const providerMap = new Map<string, ProviderAccumulator>();

  // Cumulative-width layout: each host is positioned based on the total width
  // of all preceding hosts plus the HOST_GAP between them. Width scales with
  // agents.length with no cap, so wide hosts do not collide with neighbours.
  const hostWidths = data.hosts.map((h) => hostNodeWidth(h.agents.length));
  const totalRowWidth =
    hostWidths.reduce((sum, w) => sum + w, 0) +
    Math.max(data.hosts.length - 1, 0) * HOST_GAP;
  let cursorX = -totalRowWidth / 2;

  data.hosts.forEach((host, hostIndex) => {
    const hostNodeId = `host-${host.hostname}`;
    const width = hostWidths[hostIndex];

    nodes.push({
      id: hostNodeId,
      type: "host",
      position: { x: cursorX, y: HOST_ROW_Y },
      data: {
        hostname: host.hostname,
        alias: host.alias,
        user: host.user,
        agentCount: host.agent_count,
        agents: host.agents,
        hardware: host.hardware ?? null,
        onAgentClick: opts.onAgentClick
          ? (agent: TopologyAgent) => opts.onAgentClick?.(agent, host.alias)
          : undefined,
        onHostClick: opts.onHostClick,
      },
    });

    cursorX += width + HOST_GAP;

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
      acc.agents.push({
        hostname: host.hostname,
        agentKey: agent.agent_key,
        model: agent.model || null,
      });
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

    acc.agents.forEach(({ hostname, agentKey, model }) => {
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
        ...(model
          ? {
              label: model,
              // Anchor to the design-token system; --text-secondary keeps
              // the model label readable while distinct from the SSH edge
              // label (which uses --text-muted).
              labelStyle: {
                fontSize: 9,
                fill: "var(--text-secondary)",
                opacity: 0.7,
              },
              labelBgStyle: { fill: "#FFFFFF", fillOpacity: 0.7 },
              labelBgPadding: [3, 1] as [number, number],
            }
          : {}),
      });
    });
  });

  return { nodes, edges };
}
