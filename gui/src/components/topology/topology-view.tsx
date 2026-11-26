"use client";

import { useFleetHealth } from "@/hooks/use-fleet-health";
import { useTopology } from "@/hooks/use-topology";
import { TopologyCanvas } from "./topology-canvas";

export function TopologyView() {
  const { data, isLoading, error } = useTopology();
  // Poll for live SSH-based health and merge it into the topology cache.
  useFleetHealth();

  if (isLoading) {
    return (
      <div className="bg-surface rounded-xl border border-default p-12 text-center text-muted">
        Loading topology...
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 rounded-xl border border-red-200 p-6 text-center text-red-700 text-sm">
        Failed to load topology: {error.message}
      </div>
    );
  }

  return data ? <TopologyCanvas data={data} /> : null;
}
