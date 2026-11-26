"use client";

import { AgentDetail, AgentDetailHealth } from "@/lib/types";
import { useUsageByAgent } from "@/hooks";
import { StatBlock, StatusChip } from "@/design-system";
import { AGENT_STATUS_PRESENTATION } from "@/components/ui/status-dot";

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
    { id: "uptime", label: "Uptime", value: uptime || "—", title: undefined },
    {
      id: "status",
      label: "Status",
      value: (
        <StatusChip
          trackingId="agent-detail.metrics.status-chip"
          status={status}
          label={AGENT_STATUS_PRESENTATION[status].label}
        />
      ),
      title: undefined,
    },
    {
      id: "tokens-30d",
      label: "Tokens (30d)",
      value: tokenLabel,
      title: agentUsage ? undefined : unavailableTip,
    },
    {
      id: "estimated-cost",
      label: "Est. Cost",
      value: costLabel,
      title: agentUsage ? undefined : unavailableTip,
    },
  ];

  return (
    <div className="grid grid-cols-4 gap-4">
      {metrics.map((m) => (
        <StatBlock
          key={m.id}
          trackingId={`agent-detail.metrics.${m.id}`}
          layout="stacked"
          value={m.value}
          title={m.title}
          className="dashboard-agent-metric items-center text-center"
        >
          <span className="text-xs text-muted">{m.label}</span>
        </StatBlock>
      ))}
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}
