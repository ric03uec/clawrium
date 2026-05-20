"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { type TopologyResponse, type TopologyAgent, type TopologyHost } from "@/lib/types";
import { ControlNode } from "./control-node";
import { AgentNode } from "./agent-node";
import { ProviderNode } from "./provider-node";
import { TopologyLegend } from "./topology-legend";
import { AgentInfoModal } from "./agent-info-modal";
import { HostInfoModal } from "./host-info-modal";
import { computeTopology } from "./topology-graph";

const nodeTypes = {
  control: ControlNode,
  agent: AgentNode,
  provider: ProviderNode,
};

function FleetSummaryCard({ data }: { data: TopologyResponse }) {
  const providerCount = new Set(
    data.hosts.flatMap((h) =>
      h.agents
        .map((a) => a.provider)
        .filter((p): p is string => Boolean(p))
    )
  ).size;

  const rows: { label: string; value: number; valueClass?: string }[] = [
    { label: "Hosts", value: data.summary.total_hosts },
    { label: "Agents", value: data.summary.total_agents },
    { label: "Providers", value: providerCount },
    {
      label: "Running",
      value: data.summary.running,
      valueClass: "text-status-running",
    },
  ];

  return (
    <div className="absolute top-4 left-4 bg-white/95 backdrop-blur-sm border border-default rounded-lg px-5 py-4 shadow-sm z-10 min-w-[200px]">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted mb-3">
        Fleet Summary
      </div>
      <dl className="space-y-1.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-6">
            <dt className="text-sm text-secondary">{row.label}</dt>
            <dd
              className={`text-base font-semibold tabular-nums ${
                row.valueClass ?? "text-primary-text"
              }`}
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

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
    const { nodes, edges } = computeTopology(data, {
      onAgentClick: handleAgentClick,
      onHostClick: handleHostClick,
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

      {/* Fleet summary card */}
      <FleetSummaryCard data={data} />

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
