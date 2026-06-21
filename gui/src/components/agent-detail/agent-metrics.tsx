"use client";

import { AgentDetail, AgentDetailHealth } from "@/lib/types";
import { useUsageByAgent } from "@/hooks";

interface AgentMetricsProps {
  agent: AgentDetail;
  // #758: live runtime fields. Undefined while the SSH probe is in
  // flight — uptime and status fall back to the static AgentDetail.
  health: AgentDetailHealth | undefined;
}

export function AgentMetrics({ agent, health }: AgentMetricsProps) {
  const { data: perAgent } = useUsageByAgent(30);
  const agentUsage = perAgent?.find((row) => row.agent_key === agent.agent_key);
  // uptime lives on the static endpoint (#758 S5): it's a pure
  // function of claw_record.runtime.started_at, has no SSH-derived
  // component, and the static query polls at 10s.
  const uptime = agent.uptime;
  const status = health?.status ?? agent.status;

  const tokenLabel = agentUsage
    ? formatNumber(agentUsage.tokens)
    : perAgent
    ? "—"
    : "…";
  const costLabel = agentUsage
    ? `$${agentUsage.cost.toFixed(2)}`
    : perAgent
    ? "—"
    : "…";
  const unavailableTip = "No usage recorded for this agent in the last 30 days";

  const metrics = [
    { label: "Uptime", value: uptime || "—", title: undefined },
    {
      label: "Status",
      value: status.replace("_", " "),
      title: undefined,
    },
    {
      label: "Tokens (30d)",
      value: tokenLabel,
      title: agentUsage ? undefined : unavailableTip,
    },
    {
      label: "Est. Cost",
      value: costLabel,
      title: agentUsage ? undefined : unavailableTip,
    },
  ];

  return (
    <div className="grid grid-cols-4 gap-4">
      {metrics.map((m) => (
        <div
          key={m.label}
          className="bg-white rounded-xl border border-default p-4 text-center shadow-sm"
          title={m.title}
        >
          <div className="text-lg font-semibold text-primary-text">{m.value}</div>
          <div className="text-xs text-muted mt-1">{m.label}</div>
        </div>
      ))}
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}
