"use client";

import { Provider } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const TYPE_BADGES: Record<string, { label: string; color: string }> = {
  openai: { label: "OA", color: "bg-emerald-100 text-emerald-700" },
  anthropic: { label: "AN", color: "bg-orange-100 text-orange-700" },
  openrouter: { label: "OR", color: "bg-purple-100 text-purple-700" },
  bedrock: { label: "BR", color: "bg-amber-100 text-amber-700" },
  vertex: { label: "VX", color: "bg-blue-100 text-blue-700" },
  zai: { label: "ZA", color: "bg-rose-100 text-rose-700" },
  ollama: { label: "OL", color: "bg-slate-100 text-slate-700" },
};

interface ProviderCardProps {
  provider: Provider;
  usedBy: string[];
  onEdit: () => void;
  onRemove: () => void;
}

export function ProviderCard({ provider, usedBy, onEdit, onRemove }: ProviderCardProps) {
  const badge = TYPE_BADGES[provider.type] || { label: "??", color: "bg-gray-100 text-gray-700" };

  return (
    <Card padding="md">
      <div className="flex items-start gap-4">
        {/* Type badge */}
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-sm font-bold ${badge.color}`}>
          {badge.label}
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
