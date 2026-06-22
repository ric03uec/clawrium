"use client";

import type { Integration } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IntegrationIcon } from "./integration-icon";

interface IntegrationCardProps {
  integration: Integration;
  agentsUsing: number;
  onEdit: () => void;
  onRemove: () => void;
}

export function IntegrationCard({
  integration,
  agentsUsing,
  onEdit,
  onRemove,
}: IntegrationCardProps) {
  const allConfigured =
    integration.credential_keys.length > 0 &&
    integration.credential_keys.every((k) =>
      integration.configured_credential_keys.includes(k),
    );

  return (
    <Card padding="md">
      <div className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-lg bg-white border border-default flex items-center justify-center">
          <IntegrationIcon type={integration.type} size={24} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-primary-text">
              {integration.name}
            </h3>
            <span className="text-xs text-muted uppercase">
              {integration.type}
            </span>
            {allConfigured ? (
              <span className="text-xs text-status-running">
                credentials configured
              </span>
            ) : (
              <span className="text-xs text-status-warning">
                credentials incomplete
              </span>
            )}
          </div>

          <div className="mt-1 grid grid-cols-2 gap-x-6 gap-y-0.5 text-xs text-secondary">
            <div>
              <span className="text-muted">Used by:</span>{" "}
              {agentsUsing === 0
                ? "no agents"
                : `${agentsUsing} agent${agentsUsing === 1 ? "" : "s"}`}
            </div>
            <div>
              <span className="text-muted">Keys:</span>{" "}
              {integration.configured_credential_keys.length}/
              {integration.credential_keys.length} set
            </div>
          </div>
        </div>

        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onEdit}>
            Edit credentials
          </Button>
          <Button variant="ghost" size="sm" onClick={onRemove}>
            Remove
          </Button>
        </div>
      </div>
    </Card>
  );
}
