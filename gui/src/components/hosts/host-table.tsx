"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { DataTable, StatusChip } from "@/design-system";
import { OSIcon } from "@/components/ui/os-icon";
import { useTopology } from "@/hooks/use-topology";
import type { TopologyHost } from "@/lib/types";

function primaryAddress(host: TopologyHost): string {
  const primary = host.addresses.find((address) => address.is_primary);
  return primary?.address ?? host.addresses[0]?.address ?? host.hostname;
}

const columns: ColumnDef<TopologyHost, unknown>[] = [
  {
    accessorKey: "alias",
    header: "Name",
    cell: ({ row }) => (
      <span className="inline-flex items-center gap-2 font-medium text-primary-text">
        <OSIcon os={row.original.os_family} variant="dot" size={18} />
        <span className="flex flex-col leading-tight">
          <span>{row.original.alias}</span>
          {row.original.alias !== row.original.hostname && (
            <span className="font-mono text-[11px] font-normal text-muted">{row.original.hostname}</span>
          )}
        </span>
      </span>
    ),
  },
  {
    id: "address",
    accessorFn: primaryAddress,
    header: "Address",
    cell: ({ getValue }) => <span className="font-mono text-xs text-secondary">{getValue<string>()}</span>,
  },
  {
    accessorKey: "user",
    header: "SSH user",
    cell: ({ getValue }) => <span className="font-mono text-xs text-secondary">{getValue<string>()}</span>,
  },
  {
    accessorKey: "agent_count",
    header: "Agents",
    cell: ({ getValue }) => {
      const count = getValue<number>();
      return <span className="text-secondary">{count} {count === 1 ? "agent" : "agents"}</span>;
    },
  },
  {
    id: "architecture",
    accessorFn: (host) => host.hardware?.architecture ?? "",
    header: "Architecture",
    cell: ({ getValue }) => (
      <span className="font-mono text-xs text-secondary">{getValue<string>() || "—"}</span>
    ),
  },
  {
    accessorKey: "has_key",
    header: "SSH access",
    cell: ({ getValue }) => {
      const ready = getValue<boolean>();
      return (
        <StatusChip
          trackingId="hosts.table.ssh-access"
          status={ready ? "valid" : "not_installed"}
          label={ready ? "Ready" : "Missing key"}
        />
      );
    },
  },
];

export function HostTable() {
  const { data, isLoading } = useTopology();
  const hosts = data?.hosts ?? [];

  return (
    <DataTable
      trackingId="hosts.page.table-card"
      title="Fleet Hosts"
      columns={columns}
      data={hosts}
      getRowId={(host) => host.hostname}
      isLoading={isLoading}
      loadingMessage="Loading hosts..."
      emptyMessage="No hosts registered yet"
      searchPlaceholder="Search hosts..."
      itemLabel="host"
      enablePagination={false}
    />
  );
}
