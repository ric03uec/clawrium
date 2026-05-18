"use client";

import { Provider } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { getProviderBrand } from "@/components/topology/provider-brands";

interface ProviderCardProps {
  provider: Provider;
  usedBy: string[];
  onEdit: () => void;
  onRemove: () => void;
}

export function ProviderCard({ provider, usedBy, onEdit, onRemove }: ProviderCardProps) {
  const brand = getProviderBrand(provider.type);
  const Icon = brand.Icon;

  return (
    <Card padding="md">
      <div className="flex items-start gap-4">
        {/* Provider icon */}
        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: `${brand.accentColor}15` }}
        >
          <Icon className="w-6 h-6" title={brand.label} />
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
