"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Button, DataTable } from "@/design-system";
import {
  getAcceleratorBadge,
  getProviderBrand,
} from "@/components/topology/provider-brands";
import type { Provider } from "@/lib/types";

interface ProvidersTableProps {
  providers: Provider[];
  usage: Record<string, string[]>;
  onEdit: (p: Provider) => void;
  onRemove: (p: Provider) => void;
}

export function ProvidersTable({
  providers,
  usage,
  onEdit,
  onRemove,
}: ProvidersTableProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const columns = useMemo<ColumnDef<Provider, unknown>[]>(
    () => [
      {
        id: "expand",
        header: () => <span className="sr-only">Details</span>,
        enableSorting: false,
        cell: ({ row }) => {
          const provider = row.original;
          const isExpanded = expanded === provider.name;
          const detailsId = `provider-details-${row.id}`;
          return (
            <button
              type="button"
              onClick={() => setExpanded(isExpanded ? null : provider.name)}
              className="text-muted hover:text-secondary"
              aria-label={`${isExpanded ? "Collapse" : "Expand"} details for ${provider.name}`}
              aria-expanded={isExpanded}
              aria-controls={detailsId}
            >
              {isExpanded ? "▾" : "▸"}
            </button>
          );
        },
      },
      {
        accessorKey: "name",
        header: "Provider",
        enableSorting: false,
        cell: ({ row }) => {
          const provider = row.original;
          const brand = getProviderBrand(provider.type);
          const Icon = brand.Icon;
          const isExpanded = expanded === provider.name;
          const usedBy = usage[provider.name] || [];
          return (
            <div className="min-w-64 whitespace-normal">
              <div className="flex items-center gap-2">
                <Icon className="w-5 h-5" title={brand.label} />
                <span className="font-medium text-primary-foreground">{provider.name}</span>
              </div>
              {isExpanded && (
                <ProviderDetails
                  id={`provider-details-${row.id}`}
                  provider={provider}
                  usedBy={usedBy}
                />
              )}
            </div>
          );
        },
      },
      {
        accessorKey: "type",
        header: "Type",
        enableSorting: false,
        cell: ({ getValue }) => (
          <span className="text-secondary">{getValue<string>()}</span>
        ),
      },
      {
        accessorKey: "default_model",
        header: "Default Model",
        enableSorting: false,
        cell: ({ getValue }) => (
          <span className="font-mono text-xs text-secondary">
            {getValue<string | null>() || "—"}
          </span>
        ),
      },
      {
        id: "usedBy",
        accessorFn: (provider) => (usage[provider.name] || []).join(", "),
        header: "Used by",
        enableSorting: false,
        cell: ({ row }) => {
          const usedBy = usage[row.original.name] || [];
          return usedBy.length > 0 ? (
            <span className="text-secondary">{usedBy.join(", ")}</span>
          ) : (
            <span className="px-1.5 py-0.5 text-[10px] rounded bg-surface text-muted">
              ⌀ Unassigned
            </span>
          );
        },
      },
      {
        accessorKey: "created_at",
        header: "Created",
        enableSorting: false,
        cell: ({ getValue }) => (
          <span className="text-muted">{formatDate(getValue<string | null>())}</span>
        ),
      },
      {
        id: "actions",
        header: "Actions",
        enableSorting: false,
        meta: { align: "right" },
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <Button
              trackingId="providers.table.edit"
              variant="ghost"
              size="sm"
              onClick={() => onEdit(row.original)}
            >
              Edit
            </Button>
            <Button
              trackingId="providers.table.remove"
              variant="ghost"
              size="sm"
              onClick={() => onRemove(row.original)}
            >
              Remove
            </Button>
          </div>
        ),
      },
    ],
    [expanded, onEdit, onRemove, usage],
  );

  return (
    <DataTable
      trackingId="providers.configured.table"
      columns={columns}
      data={providers}
      getRowId={(provider) => provider.name}
      itemLabel="provider"
      enableSearch={false}
      enablePagination={false}
    />
  );
}

interface ProviderDetailsProps {
  id: string;
  provider: Provider;
  usedBy: string[];
}

function ProviderDetails({ id, provider, usedBy }: ProviderDetailsProps) {
  const accelerator = getAcceleratorBadge(
    provider.type,
    provider.accelerator_vendor,
    null,
  );

  return (
    <dl
      id={id}
      className="mt-3 grid grid-cols-[140px_1fr] gap-y-1 border-t border-default pt-3 text-xs"
    >
      {provider.endpoint && (
        <>
          <dt className="text-muted">Endpoint</dt>
          <dd className="font-mono text-secondary break-all">
            {provider.endpoint}
          </dd>
        </>
      )}
      {provider.type === "bedrock" && (
        <>
          <dt className="text-muted">Region</dt>
          <dd className="font-mono text-secondary">{provider.region || "—"}</dd>
          <dt className="text-muted">AWS credentials</dt>
          <dd className="text-secondary">
            {provider.has_aws_credentials ? "configured" : "missing"}
          </dd>
        </>
      )}
      {provider.type !== "bedrock" && provider.type !== "ollama" && (
        <>
          <dt className="text-muted">API key</dt>
          <dd className="text-secondary">
            {provider.has_api_key ? "configured" : "missing"}
          </dd>
        </>
      )}
      {accelerator && (
        <>
          <dt className="text-muted">Accelerator</dt>
          <dd className="text-secondary uppercase tracking-wide text-[11px]">
            {accelerator.label}
          </dd>
        </>
      )}
      {provider.available_models && provider.available_models.length > 0 && (
        <>
          <dt className="text-muted">Models</dt>
          <dd className="text-secondary">
            {provider.available_models.slice(0, 6).join(", ")}
            {provider.available_models.length > 6 &&
              ` +${provider.available_models.length - 6} more`}
          </dd>
        </>
      )}
      {usedBy.length > 0 && (
        <>
          <dt className="text-muted">Used by</dt>
          <dd className="text-secondary">{usedBy.join(", ")}</dd>
        </>
      )}
    </dl>
  );
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toISOString().slice(0, 10);
  } catch {
    return value;
  }
}
