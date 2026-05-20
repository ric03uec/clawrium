"use client";

import { PageHeader } from "@/components/layout";
import { TopologyCanvas } from "@/components/topology";
import { useFleetHealth } from "@/hooks/use-fleet-health";
import { useTopology } from "@/hooks/use-topology";

export default function TopologyPage() {
  const { data, isLoading, error } = useTopology();
  // Poll for live SSH-based health; the hook merges results into the
  // topology cache so agent statuses leave the 'checking' state.
  useFleetHealth();

  return (
    <div>
      <PageHeader
        title="Agent Topology"
        description="Network diagram of hosts and agents"
      />

      {isLoading && (
        <div className="bg-surface rounded-xl border border-default p-12 text-center text-muted">
          Loading topology...
        </div>
      )}

      {error && (
        <div className="bg-red-50 rounded-xl border border-red-200 p-6 text-center text-red-700 text-sm">
          Failed to load topology: {error.message}
        </div>
      )}

      {data && <TopologyCanvas data={data} />}
    </div>
  );
}
