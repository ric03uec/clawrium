"use client";

import { Card } from "@/components/ui/card";
import { useFleet } from "@/hooks";
import type { AgentStatus } from "@/lib/types";

const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; bgColor: string }
> = {
  running: { label: "Running", color: "#10B981", bgColor: "#D1FAE5" },
  stopped: { label: "Stopped", color: "#EF4444", bgColor: "#FEE2E2" },
  degraded: { label: "Degraded", color: "#F59E0B", bgColor: "#FEF3C7" },
  pending_onboard: { label: "Pending", color: "#F59E0B", bgColor: "#FEF3C7" },
  onboarding: { label: "Onboarding", color: "#0EA5E9", bgColor: "#E0F2FE" },
  ready: { label: "Ready", color: "#0EA5E9", bgColor: "#E0F2FE" },
  not_installed: { label: "Not Installed", color: "#94A3B8", bgColor: "#F1F5F9" },
  unknown: { label: "Unknown", color: "#94A3B8", bgColor: "#F1F5F9" },
};

export function StatusChart() {
  const { data: fleet } = useFleet();
  const agents = fleet?.agents ?? [];

  // Count by status
  const counts: Record<string, number> = {};
  agents.forEach((a) => {
    counts[a.status] = (counts[a.status] || 0) + 1;
  });

  const entries = Object.entries(counts).sort(([, a], [, b]) => b - a);
  const total = agents.length;

  return (
    <Card padding="md" className="flex flex-col gap-4">
      <h3 className="text-sm font-medium text-secondary">Agent Status</h3>
      {total === 0 ? (
        <div className="h-48 flex items-center justify-center text-muted text-sm">
          No agents configured
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {/* Stacked bar */}
          <div className="flex h-6 rounded-full overflow-hidden">
            {entries.map(([status, count]) => {
              const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.unknown;
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
          {/* Legend */}
          <div className="flex flex-col gap-2 mt-2">
            {entries.map(([status, count]) => {
              const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.unknown;
              return (
                <div key={status} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-3 h-3 rounded-sm"
                      style={{ backgroundColor: config.color }}
                    />
                    <span className="text-sm text-secondary">
                      {config.label}
                    </span>
                  </div>
                  <span className="text-sm font-medium text-primary">
                    {count}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Card>
  );
}
