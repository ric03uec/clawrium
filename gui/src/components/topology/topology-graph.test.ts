import { describe, expect, it, vi } from "vitest";

import { type TopologyAgent, type TopologyResponse } from "@/lib/types";

import { computeTopology, providerNodeKey } from "./topology-graph";
import { AGENT_NODE_WIDTH } from "./agent-node";

function makeAgent(overrides: Partial<TopologyAgent> = {}): TopologyAgent {
  return {
    agent_key: "agent-1",
    agent_name: "agent-1",
    agent_type: "zeroclaw",
    status: "running",
    model: "m",
    version: "1.0.0",
    uptime: "1m",
    provider: "p1",
    provider_type: "ollama",
    provider_endpoint: "http://10.0.0.5:11434",
    ...overrides,
  };
}

function makeData(
  hosts: Array<{ hostname: string; alias?: string; agents: TopologyAgent[] }>
): TopologyResponse {
  return {
    control: { label: "Control", description: "clm CLI" },
    summary: {
      total_agents: hosts.reduce((n, h) => n + h.agents.length, 0),
      running: 0,
      total_hosts: hosts.length,
    },
    connections: [],
    hosts: hosts.map((h) => ({
      hostname: h.hostname,
      alias: h.alias ?? h.hostname,
      user: "alice",
      addresses: [],
      has_key: true,
      agent_count: h.agents.length,
      agents: h.agents,
    })),
  };
}

describe("computeTopology", () => {
  it("creates one agent node per agent (top-level, not nested in hosts)", () => {
    const data = makeData([
      {
        hostname: "host-a",
        agents: [makeAgent({ agent_key: "a1" }), makeAgent({ agent_key: "a2" })],
      },
      {
        hostname: "host-b",
        agents: [makeAgent({ agent_key: "b1" })],
      },
    ]);

    const { nodes } = computeTopology(data);
    const agentNodes = nodes.filter((n) => n.type === "agent");
    expect(agentNodes).toHaveLength(3);
    expect(agentNodes.map((n) => n.id).sort()).toEqual([
      "agent-a1",
      "agent-a2",
      "agent-b1",
    ]);
  });

  it("deduplicates a shared provider across two agents on different hosts", () => {
    const shared = {
      provider: "local-inx",
      provider_type: "ollama",
      provider_endpoint: "http://10.0.0.5:11434",
    };
    const data = makeData([
      {
        hostname: "host-a",
        agents: [makeAgent({ agent_key: "a1", ...shared })],
      },
      {
        hostname: "host-b",
        agents: [makeAgent({ agent_key: "b1", ...shared })],
      },
    ]);

    const { nodes, edges } = computeTopology(data);

    const providerNodes = nodes.filter((n) => n.type === "provider");
    expect(providerNodes).toHaveLength(1);

    const agentEdges = edges.filter((e) => e.target === providerNodes[0].id);
    expect(agentEdges).toHaveLength(2);
    expect(agentEdges.map((e) => e.source).sort()).toEqual([
      "agent-a1",
      "agent-b1",
    ]);
    expect(agentEdges.every((e) => e.animated === false)).toBe(true);
  });

  it("creates two provider nodes when same name has different endpoints", () => {
    const data = makeData([
      {
        hostname: "host-a",
        agents: [
          makeAgent({
            agent_key: "a1",
            provider: "ollama-local",
            provider_type: "ollama",
            provider_endpoint: "http://10.0.0.5:11434",
          }),
        ],
      },
      {
        hostname: "host-b",
        agents: [
          makeAgent({
            agent_key: "b1",
            provider: "ollama-local",
            provider_type: "ollama",
            provider_endpoint: "http://10.0.0.9:11434",
          }),
        ],
      },
    ]);

    const { nodes } = computeTopology(data);
    expect(nodes.filter((n) => n.type === "provider")).toHaveLength(2);
  });

  it("routes unconfigured agents to a single unconfigured node with dashed edges", () => {
    const data = makeData([
      {
        hostname: "host-a",
        agents: [
          makeAgent({
            agent_key: "a1",
            provider: null,
            provider_type: null,
            provider_endpoint: null,
          }),
        ],
      },
    ]);

    const { nodes, edges } = computeTopology(data);
    const providerNodes = nodes.filter((n) => n.type === "provider");
    expect(providerNodes).toHaveLength(1);

    const data_ = providerNodes[0].data as {
      unconfigured: boolean;
      agentCount: number;
    };
    expect(data_.unconfigured).toBe(true);
    expect(data_.agentCount).toBe(1);

    const edge = edges.find((e) => e.target === providerNodes[0].id);
    expect(edge).toBeDefined();
    expect((edge!.style as { strokeDasharray?: string }).strokeDasharray).toBe(
      "4 3"
    );
  });

  it("merges two unconfigured agents on different hosts into a single node with agentCount=2", () => {
    const data = makeData([
      {
        hostname: "host-a",
        agents: [
          makeAgent({
            agent_key: "a1",
            provider: null,
            provider_type: null,
            provider_endpoint: null,
          }),
        ],
      },
      {
        hostname: "host-b",
        agents: [
          makeAgent({
            agent_key: "b1",
            provider: null,
            provider_type: null,
            provider_endpoint: null,
          }),
        ],
      },
    ]);

    const { nodes, edges } = computeTopology(data);
    const providerNodes = nodes.filter((n) => n.type === "provider");
    expect(providerNodes).toHaveLength(1);
    const nodeData = providerNodes[0].data as {
      agentCount: number;
      unconfigured: boolean;
    };
    expect(nodeData.agentCount).toBe(2);
    expect(nodeData.unconfigured).toBe(true);
    const targetEdges = edges.filter((e) => e.target === providerNodes[0].id);
    expect(targetEdges).toHaveLength(2);
    targetEdges.forEach((e) =>
      expect((e.style as { strokeDasharray?: string }).strokeDasharray).toBe("4 3")
    );
  });

  it("supports zeroclaw, openclaw and nemoclaw agent types", () => {
    const data = makeData([
      {
        hostname: "host-a",
        agents: [
          makeAgent({ agent_key: "z1", agent_type: "zeroclaw" }),
          makeAgent({
            agent_key: "o1",
            agent_type: "openclaw",
            provider: "bedrock-prod",
            provider_type: "bedrock",
            provider_endpoint: null,
          }),
          makeAgent({
            agent_key: "n1",
            agent_type: "nemoclaw",
            provider: "openrouter-1",
            provider_type: "openrouter",
            provider_endpoint: null,
          }),
        ],
      },
    ]);

    const { nodes } = computeTopology(data);
    expect(nodes.filter((n) => n.type === "provider")).toHaveLength(3);
    expect(nodes.filter((n) => n.type === "agent")).toHaveLength(3);
  });

  it("threads onAgentClick and onHostClick into agent node data", () => {
    const onAgentClick = vi.fn();
    const onHostClick = vi.fn();
    const agent = makeAgent({ agent_key: "espresso" });
    const data = makeData([
      { hostname: "wolf-i", alias: "wolf-i-alias", agents: [agent] },
    ]);

    const { nodes } = computeTopology(data, { onAgentClick, onHostClick });
    const agentNode = nodes.find((n) => n.type === "agent");
    expect(agentNode).toBeDefined();
    const nodeData = agentNode!.data as {
      hostAlias: string;
      hostname: string;
      onAgentClick: (a: TopologyAgent, alias: string) => void;
      onHostClick: (h: string) => void;
    };

    // Guard the alias-vs-hostname threading invariant directly.
    expect(nodeData.hostAlias).toBe("wolf-i-alias");
    expect(nodeData.hostname).toBe("wolf-i");

    nodeData.onAgentClick(agent, nodeData.hostAlias);
    expect(onAgentClick).toHaveBeenCalledWith(agent, "wolf-i-alias");

    nodeData.onHostClick(nodeData.hostname);
    expect(onHostClick).toHaveBeenCalledWith("wolf-i");
  });

  it("leaves agent node callbacks undefined when no opts are passed", () => {
    const data = makeData([
      { hostname: "h1", agents: [makeAgent({ agent_key: "a1" })] },
    ]);
    const { nodes } = computeTopology(data);
    const agentNode = nodes.find((n) => n.type === "agent");
    const nodeData = agentNode!.data as {
      onAgentClick?: unknown;
      onHostClick?: unknown;
    };
    expect(nodeData.onAgentClick).toBeUndefined();
    expect(nodeData.onHostClick).toBeUndefined();
  });

  it("positions agent cards without overlap (AGENT_NODE_WIDTH + gap)", () => {
    const data = makeData([
      {
        hostname: "host-a",
        agents: [
          makeAgent({ agent_key: "a1" }),
          makeAgent({ agent_key: "a2" }),
          makeAgent({ agent_key: "a3" }),
        ],
      },
    ]);

    const { nodes } = computeTopology(data);
    const agentNodes = nodes
      .filter((n) => n.type === "agent")
      .sort((a, b) => a.position.x - b.position.x);

    // Each pair: left node's x + width <= right node's x
    for (let i = 0; i < agentNodes.length - 1; i++) {
      expect(agentNodes[i].position.x + AGENT_NODE_WIDTH).toBeLessThanOrEqual(
        agentNodes[i + 1].position.x
      );
    }
  });

  it("attaches the agent model name as the edge label", () => {
    const data = makeData([
      {
        hostname: "h",
        agents: [makeAgent({ agent_key: "a1", model: "claude-sonnet-4-6" })],
      },
    ]);
    const { edges } = computeTopology(data);
    const agentEdge = edges.find(
      (e) => e.source === "agent-a1" && e.target.startsWith("provider-")
    );
    expect(agentEdge?.label).toBe("claude-sonnet-4-6");
  });

  it("omits the edge label when the agent has no model set", () => {
    const data = makeData([
      {
        hostname: "h",
        agents: [makeAgent({ agent_key: "a1", model: "" })],
      },
    ]);
    const { edges } = computeTopology(data);
    const agentEdge = edges.find(
      (e) => e.source === "agent-a1" && e.target.startsWith("provider-")
    );
    expect(agentEdge?.label).toBeUndefined();
  });

  it("emits an SSH edge per agent from the control node", () => {
    const data = makeData([
      { hostname: "h1", agents: [makeAgent({ agent_key: "x1" })] },
      { hostname: "h2", agents: [makeAgent({ agent_key: "x2" })] },
    ]);
    const { edges } = computeTopology(data);
    const sshEdges = edges.filter((e) => e.source === "control");
    expect(sshEdges).toHaveLength(2);
    expect(sshEdges.every((e) => e.animated === true)).toBe(true);
    expect(sshEdges.map((e) => e.target).sort()).toEqual(["agent-x1", "agent-x2"]);
    expect(sshEdges.every((e) => e.label === "SSH")).toBe(true);
  });

  it("places control node at the bottom of the graph", () => {
    const data = makeData([
      { hostname: "h1", agents: [makeAgent({ agent_key: "a1" })] },
    ]);
    const { nodes } = computeTopology(data);
    const controlNode = nodes.find((n) => n.type === "control");
    const agentNode = nodes.find((n) => n.type === "agent");
    expect(controlNode!.position.y).toBeGreaterThan(agentNode!.position.y);
  });

  it("assigns same host color to agents on the same host", () => {
    const data = makeData([
      {
        hostname: "shared-host",
        agents: [makeAgent({ agent_key: "a1" }), makeAgent({ agent_key: "a2" })],
      },
    ]);
    const { nodes } = computeTopology(data);
    const agentNodes = nodes.filter((n) => n.type === "agent");
    const colors = agentNodes.map((n) => (n.data as { hostColor: string }).hostColor);
    expect(colors[0]).toBe(colors[1]);
  });

  it("assigns different host colors to agents on different hosts", () => {
    const data = makeData([
      { hostname: "host-a", agents: [makeAgent({ agent_key: "a1" })] },
      { hostname: "host-b", agents: [makeAgent({ agent_key: "b1" })] },
    ]);
    const { nodes } = computeTopology(data);
    const agentNodes = nodes.filter((n) => n.type === "agent");
    const colors = agentNodes.map((n) => (n.data as { hostColor: string }).hostColor);
    expect(colors[0]).not.toBe(colors[1]);
  });

  it("passes hostGpuVendor to provider node data for NVIDIA detection", () => {
    const data: TopologyResponse = {
      control: { label: "Control", description: "clm CLI" },
      summary: { total_agents: 1, running: 1, total_hosts: 1 },
      connections: [],
      hosts: [
        {
          hostname: "gpu-box",
          alias: "gpu-box",
          user: "user",
          addresses: [],
          has_key: true,
          agent_count: 1,
          agents: [makeAgent({ agent_key: "g1" })],
          hardware: {
            architecture: "x86_64",
            cores: 8,
            memtotal_mb: 32768,
            gpu: { present: true, vendor: "nvidia" },
            product_name: "DGX",
            system_vendor: "NVIDIA",
          },
        },
      ],
    };
    const { nodes } = computeTopology(data);
    const providerNode = nodes.find((n) => n.type === "provider");
    expect((providerNode!.data as { hostGpuVendor: string }).hostGpuVendor).toBe(
      "nvidia"
    );
  });
});

describe("providerNodeKey", () => {
  it("returns unconfigured key when provider and type are missing", () => {
    expect(
      providerNodeKey(
        makeAgent({
          provider: null,
          provider_type: null,
          provider_endpoint: null,
        })
      )
    ).toContain("unconfigured");
  });

  it("treats empty-string provider+type as unconfigured", () => {
    expect(
      providerNodeKey(
        makeAgent({
          provider: "",
          provider_type: "",
          provider_endpoint: null,
        })
      )
    ).toContain("unconfigured");
  });

  it("includes endpoint in the dedup key", () => {
    const k1 = providerNodeKey(
      makeAgent({ provider_endpoint: "http://a:1" })
    );
    const k2 = providerNodeKey(
      makeAgent({ provider_endpoint: "http://a:2" })
    );
    expect(k1).not.toEqual(k2);
  });

  it("does not collide for provider names containing the old '::' delimiter", () => {
    const k1 = providerNodeKey(
      makeAgent({
        provider_type: "ollama::internal",
        provider: "p",
        provider_endpoint: null,
      })
    );
    const k2 = providerNodeKey(
      makeAgent({
        provider_type: "ollama",
        provider: "internal::p",
        provider_endpoint: null,
      })
    );
    expect(k1).not.toEqual(k2);
  });
});
