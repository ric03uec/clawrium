"use client";

import { PageHeader } from "@/design-system";
import { TopologyView } from "@/components/topology";

export default function TopologyPage() {
  return (
    <div>
      <PageHeader
        trackingId="topology.page.header"
        eyebrow="Fleet map"
        title="Agent Topology"
        description="Network diagram of hosts and agents"
      />
      <TopologyView />
    </div>
  );
}
