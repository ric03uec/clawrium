import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "@/lib/api";
import type { FleetResponse, TopologyResponse } from "@/lib/types";

/**
 * Polls /api/fleet/health for live SSH-based status data and merges
 * it into both the fleet and topology query caches so agent cards
 * update progressively without a full refetch.
 */
export function useFleetHealth() {
  const queryClient = useQueryClient();

  const healthQuery = useQuery({
    queryKey: ["fleet-health"],
    queryFn: ({ signal }) => api.getFleetHealth(signal),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (!healthQuery.data) return;
    const healthData = healthQuery.data;
    const healthMap = new Map(healthData.agents.map((h) => [h.agent_key, h]));

    queryClient.setQueryData<FleetResponse>(["fleet"], (oldFleet) => {
      if (!oldFleet) return oldFleet;
      const updatedAgents = oldFleet.agents.map((agent) => {
        const health = healthMap.get(agent.agent_key);
        if (!health) return agent;
        return {
          ...agent,
          status: health.status,
          process_running: health.process_running,
          health_error: health.health_error,
          cpu_count: health.cpu_count,
          memory_total_mb: health.memory_total_mb,
          missing_secrets: health.missing_secrets,
        };
      });
      return {
        ...oldFleet,
        agents: updatedAgents,
        summary: healthData.summary,
      };
    });

    // Topology cache shares agent_keys with fleet; merge so the
    // topology view also exits the optimistic 'checking' state.
    queryClient.setQueryData<TopologyResponse>(["topology"], (oldTopology) => {
      if (!oldTopology) return oldTopology;
      let mutated = false;
      const updatedHosts = oldTopology.hosts.map((host) => {
        let hostMutated = false;
        const updatedAgents = host.agents.map((agent) => {
          const health = healthMap.get(agent.agent_key);
          if (!health || agent.status === health.status) return agent;
          hostMutated = true;
          mutated = true;
          return { ...agent, status: health.status };
        });
        return hostMutated ? { ...host, agents: updatedAgents } : host;
      });
      if (!mutated) return oldTopology;
      const running = updatedHosts.reduce(
        (n, h) => n + h.agents.filter((a) => a.status === "running").length,
        0
      );
      return {
        ...oldTopology,
        hosts: updatedHosts,
        summary: { ...oldTopology.summary, running },
      };
    });
  }, [healthQuery.data, queryClient]);

  return healthQuery;
}
