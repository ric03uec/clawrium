"use client";

import { Provider } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  getAcceleratorBadge,
  getProviderBrand,
} from "@/components/topology/provider-brands";

interface ProviderCardProps {
  provider: Provider;
  usedBy: string[];
  onEdit: () => void;
  onRemove: () => void;
}

export function ProviderCard({ provider, usedBy, onEdit, onRemove }: ProviderCardProps) {
  const brand = getProviderBrand(provider.type);
  const Icon = brand.Icon;

  // No host GPU vendor available on this page — pass null and let the
  // helper resolve from the persisted provider.accelerator_vendor.
  const accelerator = getAcceleratorBadge(
    provider.type,
    provider.accelerator_vendor,
    null,
  );

  return (
    <Card padding="md">
      <div className="flex items-start gap-4">
        {/* Provider brand tile — stacks an accelerator badge below the
            provider logo for local-inference providers so the providers
            list mirrors the topology view's branding. */}
        <div
          className="w-16 rounded-lg overflow-hidden flex-none"
          style={{ backgroundColor: `${brand.accentColor}15` }}
        >
          <div className="flex flex-col items-center py-2">
            <Icon className="w-6 h-6" title={brand.label} />
            <span className="mt-1 text-[9px] font-semibold uppercase tracking-wide text-primary-text">
              {brand.label.split(" ")[0]}
            </span>
          </div>
          {accelerator && (
            <div
              className="flex flex-col items-center py-2 border-t border-default"
              style={{ backgroundColor: `${accelerator.color}15` }}
            >
              <accelerator.Icon
                className="w-5 h-5"
                title={accelerator.label}
              />
              <span
                className="mt-1 text-[9px] font-semibold uppercase tracking-wide"
                style={{ color: accelerator.color }}
              >
                {accelerator.label}
              </span>
            </div>
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-primary-text">{provider.name}</h3>
            {provider.has_api_key && (
              <span className="text-xs text-status-running">key configured</span>
            )}
          </div>

          <div className="mt-1 grid grid-cols-2 gap-x-6 gap-y-0.5 text-xs text-secondary">
            <div>
              <span className="text-muted">Type:</span> {provider.type}
            </div>
            <div>
              <span className="text-muted">Model:</span> {provider.default_model || "—"}
            </div>
            {provider.endpoint && (
              <div className="col-span-2">
                <span className="text-muted">Endpoint:</span>{" "}
                <span className="truncate">{provider.endpoint}</span>
              </div>
            )}
            {provider.available_models && provider.available_models.length > 0 && (
              <div className="col-span-2">
                <span className="text-muted">Models:</span>{" "}
                {provider.available_models.slice(0, 3).join(", ")}
                {provider.available_models.length > 3 && ` +${provider.available_models.length - 3} more`}
              </div>
            )}
            {usedBy.length > 0 && (
              <div className="col-span-2">
                <span className="text-muted">Used by:</span> {usedBy.join(", ")}
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onEdit}>
            Edit
          </Button>
          <Button variant="ghost" size="sm" onClick={onRemove}>
            Remove
          </Button>
        </div>
      </div>
    </Card>
  );
}
