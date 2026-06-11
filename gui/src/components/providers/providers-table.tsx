"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
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

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-default text-left">
            <th className="pb-3 pr-4 font-medium text-muted w-8"></th>
            <th className="pb-3 pr-4 font-medium text-muted">Provider</th>
            <th className="pb-3 pr-4 font-medium text-muted">Type</th>
            <th className="pb-3 pr-4 font-medium text-muted">Default Model</th>
            <th className="pb-3 pr-4 font-medium text-muted">Used by</th>
            <th className="pb-3 pr-4 font-medium text-muted">Created</th>
            <th className="pb-3 font-medium text-muted text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {providers.map((p) => {
            const brand = getProviderBrand(p.type);
            const Icon = brand.Icon;
            const usedBy = usage[p.name] || [];
            const isOpen = expanded === p.name;
            return (
              <ProviderRow
                key={p.name}
                provider={p}
                brandIcon={<Icon className="w-5 h-5" title={brand.label} />}
                usedBy={usedBy}
                expanded={isOpen}
                onToggle={() => setExpanded(isOpen ? null : p.name)}
                onEdit={() => onEdit(p)}
                onRemove={() => onRemove(p)}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface ProviderRowProps {
  provider: Provider;
  brandIcon: React.ReactNode;
  usedBy: string[];
  expanded: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onRemove: () => void;
}

function ProviderRow({
  provider,
  brandIcon,
  usedBy,
  expanded,
  onToggle,
  onEdit,
  onRemove,
}: ProviderRowProps) {
  const accelerator = getAcceleratorBadge(
    provider.type,
    provider.accelerator_vendor,
    null,
  );

  return (
    <>
      <tr className="border-b border-default last:border-0 hover:bg-surface">
        <td className="py-3 pr-4 align-middle">
          <button
            type="button"
            onClick={onToggle}
            className="text-muted hover:text-secondary"
            aria-label={expanded ? "Collapse details" : "Expand details"}
          >
            {expanded ? "▾" : "▸"}
          </button>
        </td>
        <td className="py-3 pr-4">
          <div className="flex items-center gap-2">
            {brandIcon}
            <span className="font-medium text-primary">{provider.name}</span>
          </div>
        </td>
        <td className="py-3 pr-4 text-secondary">{provider.type}</td>
        <td className="py-3 pr-4 text-secondary font-mono text-xs">
          {provider.default_model || "—"}
        </td>
        <td className="py-3 pr-4 text-secondary">
          {usedBy.length > 0 ? (
            usedBy.join(", ")
          ) : (
            <span className="px-1.5 py-0.5 text-[10px] rounded bg-surface text-muted">
              ⌀ Unassigned
            </span>
          )}
        </td>
        <td className="py-3 pr-4 text-muted whitespace-nowrap">
          {formatDate(provider.created_at)}
        </td>
        <td className="py-3 text-right whitespace-nowrap">
          <Button variant="ghost" size="sm" onClick={onEdit}>
            Edit
          </Button>
          <Button variant="ghost" size="sm" onClick={onRemove}>
            Remove
          </Button>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-default bg-surface/50">
          <td></td>
          <td colSpan={6} className="py-3 pr-4">
            <dl className="grid grid-cols-[140px_1fr] gap-y-1 text-xs">
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
                  <dd className="font-mono text-secondary">
                    {provider.region || "—"}
                  </dd>
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
              {provider.available_models &&
                provider.available_models.length > 0 && (
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
          </td>
        </tr>
      )}
    </>
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
