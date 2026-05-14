"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { type TopologyResponse, type TopologyAgent, type TopologyHost } from "@/lib/types";
import { ControlNode } from "./control-node";
import { HostNode } from "./host-node";
import { TopologyLegend } from "./topology-legend";
import { AgentInfoModal } from "./agent-info-modal";
import { HostInfoModal } from "./host-info-modal";

const nodeTypes = {
  control: ControlNode,
  host: HostNode,
};

interface TopologyCanvasProps {
  data: TopologyResponse;
}

export function TopologyCanvas({ data }: TopologyCanvasProps) {
  const [selectedAgent, setSelectedAgent] = useState<TopologyAgent | null>(null);
  const [selectedAgentHost, setSelectedAgentHost] = useState<string>("");
  const [selectedHost, setSelectedHost] = useState<TopologyHost | null>(null);

  const handleAgentClick = useCallback(
    (agent: TopologyAgent, hostAlias: string) => {
      setSelectedAgent(agent);
      setSelectedAgentHost(hostAlias);
    },
    []
  );

  const handleHostClick = useCallback(
    (hostname: string) => {
      const host = data.hosts.find((h) => h.hostname === hostname);
      if (host) setSelectedHost(host);
    },
    [data.hosts]
  );

  const { initialNodes, initialEdges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];

    // Control node at top center
    nodes.push({
      id: "control",
      type: "control",
      position: { x: 0, y: 0 },
      data: {
        label: data.control.label,
        description: data.control.description,
      },
    });

    // Host nodes in a row below
    const hostSpacing = 300;
    const totalWidth = (data.hosts.length - 1) * hostSpacing;
    const startX = -totalWidth / 2;

    data.hosts.forEach((host, index) => {
      const nodeId = `host-${host.hostname}`;

      nodes.push({
        id: nodeId,
        type: "host",
        position: { x: startX + index * hostSpacing, y: 180 },
        data: {
          hostname: host.hostname,
          alias: host.alias,
          user: host.user,
          agentCount: host.agent_count,
          agents: host.agents,
          onAgentClick: (agent: TopologyAgent) =>
            handleAgentClick(agent, host.alias),
          onHostClick: handleHostClick,
        },
      });

      // SSH connection edge
      edges.push({
        id: `edge-control-${host.hostname}`,
        source: "control",
        target: nodeId,
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
    });

    return { initialNodes: nodes, initialEdges: edges };
  }, [data, handleAgentClick, handleHostClick]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // useNodesState/useEdgesState consume their argument only at mount. The
  // hook refetches every 30s and recomputes initialNodes/initialEdges via
  // useMemo — without this effect, the canvas froze at first load.
  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  return (
    <div className="relative w-full h-[calc(100vh-12rem)] bg-surface rounded-xl border border-default overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={2}
      >
        <Background color="#E2E8F0" gap={20} size={1} />
        <Controls
          showInteractive={false}
          className="!bg-white !border-default !shadow-sm !rounded-lg"
        />
      </ReactFlow>

      <TopologyLegend />

      {/* Summary badge */}
      <div className="absolute top-4 right-4 bg-white/90 backdrop-blur-sm border border-default rounded-lg px-4 py-2 shadow-sm z-10">
        <div className="flex items-center gap-4 text-xs">
          <span className="text-muted">
            Hosts: <span className="font-medium text-primary-text">{data.summary.total_hosts}</span>
          </span>
          <span className="text-muted">
            Agents: <span className="font-medium text-primary-text">{data.summary.total_agents}</span>
          </span>
          <span className="text-muted">
            Running: <span className="font-medium text-status-running">{data.summary.running}</span>
          </span>
        </div>
      </div>

      {/* Modals */}
      <AgentInfoModal
        agent={selectedAgent}
        hostAlias={selectedAgentHost}
        onClose={() => setSelectedAgent(null)}
      />
      <HostInfoModal
        host={selectedHost}
        onClose={() => setSelectedHost(null)}
      />
    </div>
  );
}
