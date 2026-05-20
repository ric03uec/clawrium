import { MarkerType, type Edge, type Node } from "@xyflow/react";

import {
  type AcceleratorVendor,
  type TopologyAgent,
  type TopologyResponse,
} from "@/lib/types";
import { buildHostColorMap, getHostColor } from "./host-colors";
import { AGENT_NODE_WIDTH } from "./agent-node";

/* ─── Layout Constants ────────────────────────────────────────────── */

/** Vertical row positions (top → bottom) */
const AGENT_ROW_Y = 0;
const PROVIDER_ROW_Y = 320;
const CONTROL_ROW_Y = 560;

/** Horizontal spacing between agent cards */
const AGENT_GAP = 36;

/** Horizontal spacing between provider nodes */
const PROVIDER_SPACING = 200;

const UNCONFIGURED_KEY = "__unconfigured__";

/* ─── Types ───────────────────────────────────────────────────────── */

export interface ProviderNodeData {
  providerKey: string;
  name: string;
  type: string | null;
  endpoint: string | null;
  agentCount: number;
  unconfigured: boolean;
  hostGpuVendor?: string | null;
  /** User-selected accelerator brand for local-inference providers. */
  acceleratorVendor?: AcceleratorVendor | null;
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
  /** GPU vendor of the first host (for NVIDIA local inference detection) */
  hostGpuVendor: string | null;
  /** User-selected accelerator brand from provider record. */
  acceleratorVendor: AcceleratorVendor | null;
  agents: Array<{ hostname: string; agentKey: string; model: string | null }>;
}

/* ─── Helpers ─────────────────────────────────────────────────────── */

export function providerNodeKey(agent: TopologyAgent): string {
  if (!agent.provider && !agent.provider_type) return UNCONFIGURED_KEY;
  const type = agent.provider_type || "unknown";
  const name = agent.provider || type;
  const endpoint = agent.provider_endpoint ?? "";
  return [type, name, endpoint].map(encodeURIComponent).join("|");
}

/* ─── Main Layout Function ────────────────────────────────────────── */

export function computeTopology(
  data: TopologyResponse,
  opts: ComputeTopologyOptions = {}
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // ─── Build host color map ─────────────────────────────────────────
  const hostnames = data.hosts.map((h) => h.hostname);
  const hostColorMap = buildHostColorMap(hostnames);

  // ─── 1. Agent nodes (top row) ─────────────────────────────────────
  // Flatten all agents across hosts into individual top-level nodes.
  const allAgents: Array<{
    agent: TopologyAgent;
    hostname: string;
    alias: string;
    hardware: TopologyResponse["hosts"][0]["hardware"];
  }> = [];

  data.hosts.forEach((host) => {
    host.agents.forEach((agent) => {
      allAgents.push({
        agent,
        hostname: host.hostname,
        alias: host.alias,
        hardware: host.hardware,
      });
    });
  });

  const totalAgentWidth =
    allAgents.length * AGENT_NODE_WIDTH +
    Math.max(allAgents.length - 1, 0) * AGENT_GAP;
  let agentCursorX = -totalAgentWidth / 2;

  allAgents.forEach(({ agent, hostname, alias, hardware }) => {
    const nodeId = `agent-${agent.agent_key}`;
    nodes.push({
      id: nodeId,
      type: "agent",
      position: { x: agentCursorX, y: AGENT_ROW_Y },
      data: {
        agent,
        hostname,
        hostAlias: alias,
        hardware: hardware ?? null,
        hostColor: getHostColor(hostColorMap, hostname),
        onAgentClick: opts.onAgentClick,
        onHostClick: opts.onHostClick,
      },
    });
    agentCursorX += AGENT_NODE_WIDTH + AGENT_GAP;
  });

  // ─── 2. Provider nodes (middle row) ──────────────────────────────
  const providerOrder: string[] = [];
  const providerMap = new Map<string, ProviderAccumulator>();

  data.hosts.forEach((host) => {
    host.agents.forEach((agent) => {
      const pKey = providerNodeKey(agent);
      let acc = providerMap.get(pKey);
      if (!acc) {
        const unconfigured = pKey === UNCONFIGURED_KEY;
        acc = {
          key: pKey,
          name: unconfigured
            ? "Unconfigured"
            : agent.provider || agent.provider_type || "Unknown",
          type: unconfigured ? null : agent.provider_type ?? null,
          endpoint: unconfigured ? null : agent.provider_endpoint ?? null,
          unconfigured,
          hostGpuVendor: host.hardware?.gpu?.vendor ?? null,
          acceleratorVendor: agent.provider_accelerator_vendor ?? null,
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
        hostGpuVendor: acc.hostGpuVendor,
        acceleratorVendor: acc.acceleratorVendor,
      } satisfies ProviderNodeData,
    });

    // Edges: agent → provider
    acc.agents.forEach(({ agentKey, model }) => {
      const stroke = acc.unconfigured ? "#94A3B8" : "#475569";
      edges.push({
        id: `edge-${agentKey}-${pKey}`,
        source: `agent-${agentKey}`,
        sourceHandle: "provider",
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

  // ─── 3. Control node (bottom row, minimal) ────────────────────────
  nodes.push({
    id: "control",
    type: "control",
    position: { x: 0, y: CONTROL_ROW_Y },
    data: { label: data.control.label, description: data.control.description },
  });

  // Edges: control → agent (SSH, dashed + animated)
  allAgents.forEach(({ agent }) => {
    edges.push({
      id: `edge-control-${agent.agent_key}`,
      source: "control",
      target: `agent-${agent.agent_key}`,
      targetHandle: "ssh",
      type: "default",
      animated: true,
      style: { stroke: "#0D9488", strokeWidth: 1, strokeDasharray: "5 3" },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: "#0D9488",
        width: 12,
        height: 12,
      },
      label: "SSH",
      labelStyle: { fontSize: 9, fill: "#94A3B8" },
      labelBgStyle: { fill: "#FFFFFF", fillOpacity: 0.8 },
      labelBgPadding: [3, 1] as [number, number],
    });
  });

  return { nodes, edges };
}
