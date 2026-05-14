"use client";

import { Card, Button } from "@/components/ui";

export function DangerZoneCard() {
  return (
    <Card>
      <h2 className="text-lg font-semibold text-status-error mb-4">
        Danger Zone
      </h2>
      <p className="text-sm text-secondary mb-4">
        Destructive actions that cannot be undone. Use with caution.
      </p>
      <Button
        variant="danger"
        size="sm"
        disabled
        title="Reset is not implemented yet — track in issue #N (see FOLLOWUPS.md)"
      >
        Reset All Configuration
      </Button>
      <p className="mt-2 text-xs text-muted">
        Reset wiring isn&apos;t implemented yet. Use{" "}
        <code className="font-mono">clm host</code> /{" "}
        <code className="font-mono">clm agent</code> /{" "}
        <code className="font-mono">clm provider</code> CLI commands to remove
        config in the meantime.
      </p>
    </Card>
  );
}
