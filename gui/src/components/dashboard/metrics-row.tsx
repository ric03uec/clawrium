"use client";

import { useFleet, useProviders, useUsageSummary } from "@/hooks";
import { MetricCard } from "./metric-card";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(n: number): string {
  if (n >= 100) return `$${n.toFixed(0)}`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n > 0) return `$${n.toFixed(3)}`;
  return "$0.00";
}

export function MetricsRow() {
  const { data: fleet } = useFleet();
  const { data: providers } = useProviders();
  const { data: usage } = useUsageSummary(1); // 24h

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
      <MetricCard
        label="Total Agents"
        value={fleet?.summary.total ?? 0}
      />
      <MetricCard
        label="Running"
        value={fleet?.summary.running ?? 0}
        sublabel={fleet ? `of ${fleet.summary.total}` : undefined}
      />
      <MetricCard
        label="Providers"
        value={providers?.length ?? 0}
      />
      <MetricCard
        label="Tokens (24h)"
        value={formatTokens(usage?.total_tokens ?? 0)}
        sublabel={`${usage?.total_requests ?? 0} requests`}
      />
      <MetricCard
        label="Est. Cost (24h)"
        value={formatCost(usage?.total_cost ?? 0)}
      />
    </div>
  );
}
