"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { AgentLogo, DataTable } from "@/design-system";
import { StatusDot } from "@/components/ui/status-dot";
import { OSIcon } from "@/components/ui/os-icon";
import { useFleet, useFleetHealth } from "@/hooks";
import type { AgentSummary } from "@/lib/types";

const columns: ColumnDef<AgentSummary, unknown>[] = [
  {
    accessorKey: "status",
    header: () => <span className="sr-only">Status</span>,
    cell: ({ row }) => <StatusDot status={row.original.status} size="md" />,
  },
  {
    accessorKey: "agent_name",
    header: "Name",
    cell: ({ row }) => (
      <Link
        href={`/agents?key=${encodeURIComponent(row.original.agent_key)}`}
        aria-label={`Open agent ${row.original.agent_name}`}
        className="inline-flex items-center gap-2 font-medium text-primary-foreground hover:underline"
      >
        <AgentLogo
          trackingId="dashboard.agents.agent-logo"
          kind={row.original.agent_type}
          size={16}
        />
        {row.original.agent_name}
      </Link>
    ),
  },
  {
    accessorKey: "agent_type",
    header: "Type",
    cell: ({ getValue }) => <span className="text-secondary">{getValue<string>()}</span>,
  },
  {
    id: "host",
    accessorFn: (agent) => agent.host_alias || agent.host,
    header: "Host",
    cell: ({ row, getValue }) => (
      <span className="inline-flex items-center gap-1.5 text-secondary">
        <OSIcon os={row.original.host_os_family} variant="dot" />
        {getValue<string>()}
      </span>
    ),
  },
  {
    accessorKey: "model",
    header: "Model",
    cell: ({ getValue }) => (
      <span className="font-mono text-xs text-secondary">{getValue<string>() || "—"}</span>
    ),
  },
  {
    accessorKey: "uptime",
    header: "Uptime",
    cell: ({ getValue }) => <span className="text-secondary">{getValue<string>() || "—"}</span>,
  },
];

export function AgentTable() {
  const { data: fleet, isLoading } = useFleet();
  // Start health polling — merges live status into fleet cache
  useFleetHealth();
  const agents = fleet?.agents ?? [];

  return (
    <DataTable
      trackingId="dashboard.agents.table-card"
      title="Fleet Agents"
      columns={columns}
      data={agents}
      getRowId={(agent) => agent.agent_key}
      isLoading={isLoading}
      loadingMessage="Loading..."
      emptyMessage="No agents installed yet"
      itemLabel="agent"
      enableSearch={false}
      enablePagination={false}
    />
  );
}
