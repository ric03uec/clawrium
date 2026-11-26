"use client";

import { Card, StatusLight } from "@/design-system";
import { AGENT_STATUS_PRESENTATION } from "@/components/ui/status-dot";
import { useFleet } from "@/hooks";
import type { AgentStatus } from "@/lib/types";

export function StatusChart() {
  const { data: fleet } = useFleet();
  const agents = fleet?.agents ?? [];

  const counts: Record<string, number> = {};
  agents.forEach((agent) => {
    counts[agent.status] = (counts[agent.status] || 0) + 1;
  });

  const entries = Object.entries(counts).sort(([, a], [, b]) => b - a);
  const total = agents.length;

  return (
    <Card trackingId="dashboard.status.chart-card" padding="md" className="flex flex-col gap-4">
      <h3 className="text-sm font-medium text-secondary">Agent Status</h3>
      {total === 0 ? (
        <div className="h-48 flex items-center justify-center text-muted text-sm">
          No agents configured
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex h-6 rounded-full overflow-hidden">
            {entries.map(([status, count]) => {
              const config =
                AGENT_STATUS_PRESENTATION[status as AgentStatus] ?? AGENT_STATUS_PRESENTATION.unknown;
              const pct = (count / total) * 100;
              return (
                <div
                  key={status}
                  className="h-full transition-all"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: config.color,
                    minWidth: count > 0 ? "8px" : "0",
                  }}
                  title={`${config.label}: ${count}`}
                />
              );
            })}
          </div>
          <div className="flex flex-col gap-2 mt-2">
            {entries.map(([status, count]) => {
              const config =
                AGENT_STATUS_PRESENTATION[status as AgentStatus] ?? AGENT_STATUS_PRESENTATION.unknown;
              return (
                <div key={status} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <StatusLight
                      trackingId={`dashboard.status.${status.replaceAll("_", "-")}`}
                      tone={config.tone}
                      className={config.pulse ? "animate-pulse" : undefined}
                    />
                    <span className="text-sm text-secondary">{config.label}</span>
                  </div>
                  <span className="text-sm font-medium text-primary-foreground">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Card>
  );
}
