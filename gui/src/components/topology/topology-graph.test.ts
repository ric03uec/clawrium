import { describe, expect, it } from "vitest";

import { type TopologyAgent, type TopologyResponse } from "@/lib/types";

import { computeTopology, providerNodeKey } from "./topology-graph";

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
    expect(agentEdges.map((e) => e.sourceHandle).sort()).toEqual(["a1", "b1"]);
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

    const { nodes, edges } = computeTopology(data);
    expect(nodes.filter((n) => n.type === "provider")).toHaveLength(3);

    const handles = edges
      .filter((e) => e.source === "host-host-a")
      .map((e) => e.sourceHandle)
      .filter(Boolean)
      .sort();
    expect(handles).toEqual(["n1", "o1", "z1"]);
  });

  it("emits an SSH edge per host as before", () => {
    const data = makeData([
      { hostname: "h1", agents: [] },
      { hostname: "h2", agents: [] },
    ]);
    const { edges } = computeTopology(data);
    const sshEdges = edges.filter((e) => e.source === "control");
    expect(sshEdges).toHaveLength(2);
    expect(sshEdges.every((e) => e.animated === true)).toBe(true);
    expect(sshEdges.map((e) => e.target).sort()).toEqual(["host-h1", "host-h2"]);
    expect(sshEdges.every((e) => e.label === "SSH")).toBe(true);
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
