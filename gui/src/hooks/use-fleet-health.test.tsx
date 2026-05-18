import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useFleetHealth } from "./use-fleet-health";
import { api } from "@/lib/api";
import type {
  AgentSummary,
  FleetHealthResponse,
  FleetResponse,
  TopologyResponse,
} from "@/lib/types";

function makeFleet(): FleetResponse {
  const agents: AgentSummary[] = [
    {
      agent_key: "a1",
      agent_name: "a1",
      agent_type: "openclaw",
      host: "h1",
      host_alias: "h1",
      status: "checking",
      model: "m",
      uptime: "1m",
      gateway_url: null,
    },
    {
      agent_key: "a2",
      agent_name: "a2",
      agent_type: "zeroclaw",
      host: "h1",
      host_alias: "h1",
      status: "checking",
      model: "m",
      uptime: "1m",
      gateway_url: null,
    },
  ];
  return {
    agents,
    summary: { total: 2, running: 0, provisioning: 0, hosts: 1 },
  };
}

function makeTopology(): TopologyResponse {
  return {
    control: { label: "control", description: "" },
    connections: [],
    summary: { total_agents: 2, running: 0, total_hosts: 1 },
    hosts: [
      {
        hostname: "h1",
        alias: "h1",
        user: "u",
        addresses: [],
        has_key: true,
        agent_count: 2,
        agents: [
          {
            agent_key: "a1",
            agent_name: "a1",
            agent_type: "openclaw",
            status: "checking",
            model: "m",
            version: "v",
            uptime: "1m",
            provider: null,
            provider_type: null,
            provider_endpoint: null,
          },
          {
            agent_key: "a2",
            agent_name: "a2",
            agent_type: "zeroclaw",
            status: "checking",
            model: "m",
            version: "v",
            uptime: "1m",
            provider: null,
            provider_type: null,
            provider_endpoint: null,
          },
        ],
      },
    ],
  };
}

function makeHealth(): FleetHealthResponse {
  return {
    summary: { total: 2, running: 1, provisioning: 0, hosts: 1 },
    agents: [
      {
        agent_key: "a1",
        status: "running",
        process_running: true,
        health_error: null,
        cpu_count: 4,
        memory_total_mb: 8192,
        missing_secrets: null,
      },
      {
        agent_key: "a2",
        status: "stopped",
        process_running: false,
        health_error: null,
        cpu_count: 4,
        memory_total_mb: 8192,
        missing_secrets: null,
      },
    ],
  };
}

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: 0 },
    },
  });
}

function makeWrapper(client: QueryClient) {
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "QueryWrapper";
  return Wrapper;
}

describe("useFleetHealth", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("merges health data into the fleet cache", async () => {
    const client = makeClient();
    client.setQueryData(["fleet"], makeFleet());

    vi.spyOn(api, "getFleetHealth").mockResolvedValue(makeHealth());

    renderHook(() => useFleetHealth(), { wrapper: makeWrapper(client) });

    await waitFor(() => {
      const fleet = client.getQueryData<FleetResponse>(["fleet"]);
      expect(fleet?.agents[0].status).toBe("running");
    });

    const fleet = client.getQueryData<FleetResponse>(["fleet"])!;
    expect(fleet.agents[0].process_running).toBe(true);
    expect(fleet.agents[0].cpu_count).toBe(4);
    expect(fleet.agents[1].status).toBe("stopped");
    expect(fleet.summary.running).toBe(1);
  });

  it("merges status updates into the topology cache and recomputes running count", async () => {
    const client = makeClient();
    client.setQueryData(["topology"], makeTopology());

    vi.spyOn(api, "getFleetHealth").mockResolvedValue(makeHealth());

    renderHook(() => useFleetHealth(), { wrapper: makeWrapper(client) });

    await waitFor(() => {
      const topo = client.getQueryData<TopologyResponse>(["topology"]);
      expect(topo?.hosts[0].agents[0].status).toBe("running");
    });

    const topo = client.getQueryData<TopologyResponse>(["topology"])!;
    expect(topo.hosts[0].agents[1].status).toBe("stopped");
    expect(topo.summary.running).toBe(1);
  });

  it("is a no-op when there is no existing fleet or topology cache", async () => {
    const client = makeClient();

    vi.spyOn(api, "getFleetHealth").mockResolvedValue(makeHealth());

    const { result } = renderHook(() => useFleetHealth(), {
      wrapper: makeWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(client.getQueryData(["fleet"])).toBeUndefined();
    expect(client.getQueryData(["topology"])).toBeUndefined();
  });

  it("does not blow away an existing fleet agent when health omits its key", async () => {
    const client = makeClient();
    client.setQueryData(["fleet"], makeFleet());

    vi.spyOn(api, "getFleetHealth").mockResolvedValue({
      summary: { total: 2, running: 0, provisioning: 0, hosts: 1 },
      agents: [
        // Only a1 reports — a2 must be left untouched at 'checking'.
        {
          agent_key: "a1",
          status: "running",
          process_running: true,
          health_error: null,
          cpu_count: 2,
          memory_total_mb: 4096,
          missing_secrets: null,
        },
      ],
    });

    renderHook(() => useFleetHealth(), { wrapper: makeWrapper(client) });

    await waitFor(() => {
      const fleet = client.getQueryData<FleetResponse>(["fleet"]);
      expect(fleet?.agents[0].status).toBe("running");
    });

    const fleet = client.getQueryData<FleetResponse>(["fleet"])!;
    expect(fleet.agents[1].agent_key).toBe("a2");
    expect(fleet.agents[1].status).toBe("checking");
  });

  it("passes the AbortSignal from TanStack Query into the api call", async () => {
    const client = makeClient();
    const spy = vi.spyOn(api, "getFleetHealth").mockResolvedValue(makeHealth());

    const { result } = renderHook(() => useFleetHealth(), {
      wrapper: makeWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(spy).toHaveBeenCalled();
    const signal = spy.mock.calls[0][0];
    expect(signal).toBeInstanceOf(AbortSignal);
  });

  it("configures a 10s refetch interval", () => {
    const client = makeClient();
    vi.spyOn(api, "getFleetHealth").mockResolvedValue(makeHealth());

    renderHook(() => useFleetHealth(), { wrapper: makeWrapper(client) });

    const queries = client.getQueryCache().findAll({ queryKey: ["fleet-health"] });
    expect(queries).toHaveLength(1);
    const opts = queries[0].observers[0]?.options as
      | { refetchInterval?: unknown }
      | undefined;
    expect(opts?.refetchInterval).toBe(10_000);
  });
});
