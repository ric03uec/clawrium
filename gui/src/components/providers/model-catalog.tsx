"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/design-system";
import { useProviderTypes, useModelCatalog } from "@/hooks/use-providers";
import type { CatalogModel, ProviderTypeInfo } from "@/lib/types";

const PAGE_SIZE = 50;

export function ModelCatalog() {
  const { data: providerTypes, isLoading: typesLoading } = useProviderTypes();
  const [selected, setSelected] = useState<string>("__all__");

  const typeEntries = useMemo(() => {
    if (!providerTypes) return [];
    return Object.entries(providerTypes).sort((a, b) =>
      a[0].localeCompare(b[0]),
    );
  }, [providerTypes]);

  const totalAllModels = useMemo(
    () =>
      typeEntries.reduce(
        (sum, [, info]) => sum + (info.models?.length ?? 0),
        0,
      ),
    [typeEntries],
  );

  const isAll = selected === "__all__";
  const isOllama = selected === "ollama";
  const { data: models, isLoading: modelsLoading } = useModelCatalog(
    isAll || isOllama ? undefined : selected,
    undefined,
    isAll ? 500 : undefined,
  );

  const columns = useMemo<ColumnDef<CatalogModel, unknown>[]>(
    () => modelColumns(isAll),
    [isAll],
  );

  const providerSelector = (
    <ProviderSelector
      selected={selected}
      typeEntries={typeEntries}
      totalAllModels={totalAllModels}
      onChange={setSelected}
    />
  );

  if (typesLoading) {
    return (
      <div className="py-8 text-center text-sm text-muted">
        Loading registry...
      </div>
    );
  }

  if (isOllama) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex justify-end">{providerSelector}</div>
        <div className="py-8 text-center text-sm text-muted">
          Models are discovered per-host from the Ollama daemon. See the
          configured Ollama provider in the Configured tab.
        </div>
      </div>
    );
  }

  return (
    <DataTable
      key={selected}
      trackingId="providers.registry.model-catalog"
      columns={columns}
      data={models ?? []}
      getRowId={(model) => `${model.provider_type}:${model.id}`}
      pageSize={PAGE_SIZE}
      itemLabel="model"
      searchPlaceholder="Search models..."
      headerActions={providerSelector}
      isLoading={modelsLoading}
      loadingMessage="Loading models..."
      emptyMessage="No models found"
      noResultsMessage="No models found"
    />
  );
}

interface ProviderSelectorProps {
  selected: string;
  typeEntries: [string, ProviderTypeInfo][];
  totalAllModels: number;
  onChange: (value: string) => void;
}

function ProviderSelector({
  selected,
  typeEntries,
  totalAllModels,
  onChange,
}: ProviderSelectorProps) {
  return (
    <select
      aria-label="Model provider"
      value={selected}
      onChange={(event) => onChange(event.target.value)}
      className="px-3 py-1.5 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30"
    >
      <option value="__all__">All providers ({totalAllModels} models)</option>
      {typeEntries.map(([providerType, info]) => {
        const count = info.models?.length ?? 0;
        const countLabel =
          providerType === "ollama"
            ? "per-host"
            : count > 0
              ? `${count} models`
              : "—";
        return (
          <option key={providerType} value={providerType}>
            {providerType} ({countLabel})
          </option>
        );
      })}
    </select>
  );
}

function modelColumns(isAll: boolean): ColumnDef<CatalogModel, unknown>[] {
  const columns: ColumnDef<CatalogModel, unknown>[] = [];

  if (isAll) {
    columns.push({
      accessorKey: "provider_type",
      header: "Provider",
      enableSorting: false,
      enableGlobalFilter: false,
      cell: ({ getValue }) => (
        <span className="text-secondary">{getValue<string>()}</span>
      ),
    });
  }

  columns.push(
    {
      id: "model",
      accessorFn: (model) => `${model.id} ${model.name || ""}`,
      header: "Model",
      enableSorting: false,
      cell: ({ row }) => (
        <span className="font-medium text-primary-text font-mono">
          {row.original.id}
        </span>
      ),
    },
    {
      accessorKey: "context_window",
      header: "Context",
      enableSorting: false,
      enableGlobalFilter: false,
      cell: ({ getValue }) => (
        <span className="text-secondary">
          {formatContext(getValue<number>())}
        </span>
      ),
    },
    {
      accessorKey: "tags",
      header: "Tags",
      enableSorting: false,
      enableGlobalFilter: false,
      cell: ({ getValue }) => (
        <div className="flex gap-1 flex-wrap">
          {getValue<string[]>().map((tag) => (
            <span
              key={tag}
              className="px-1.5 py-0.5 bg-surface text-muted rounded text-[10px]"
            >
              {tag}
            </span>
          ))}
        </div>
      ),
    },
  );

  return columns;
}

function formatContext(windowSize: number): string {
  if (windowSize >= 1000000) return `${(windowSize / 1000000).toFixed(1)}M`;
  if (windowSize >= 1000) return `${Math.round(windowSize / 1000)}K`;
  return String(windowSize);
}
