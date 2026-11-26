"use client";

import { useState } from "react";
import { Button, Card } from "@/design-system";

export function DangerZoneCard() {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [result, setResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  const handleReset = async () => {
    setResetting(true);
    setResult(null);
    try {
      const resp = await fetch("/api/settings/reset", { method: "POST" });
      if (resp.ok) {
        setResult({
          success: true,
          message:
            "Configuration reset complete. Refresh the page to see changes.",
        });
      } else {
        const data = await resp.json().catch(() => null);
        setResult({
          success: false,
          message: data?.detail ?? `Reset failed (HTTP ${resp.status})`,
        });
      }
    } catch (err) {
      setResult({
        success: false,
        message: err instanceof Error ? err.message : "Network error",
      });
    } finally {
      setResetting(false);
      setConfirmOpen(false);
    }
  };

  return (
    <Card trackingId="settings.danger-zone.card">
      <h2 className="text-lg font-semibold text-status-error mb-4">
        Danger Zone
      </h2>
      <p className="text-sm text-secondary mb-4">
        Destructive actions that cannot be undone. Use with caution.
      </p>

      {!confirmOpen ? (
        <Button trackingId="settings.danger-zone.open"
          variant="danger"
          size="sm"
          onClick={() => setConfirmOpen(true)}
        >
          Reset All Configuration
        </Button>
      ) : (
        <div className="space-y-3 p-3 border border-status-error/30 rounded bg-red-50">
          <p className="text-sm text-primary-text font-medium">
            Are you sure? This will remove:
          </p>
          <ul className="text-xs text-secondary list-disc ml-4 space-y-1">
            <li>All provider configurations and API keys</li>
            <li>All integration credentials</li>
            <li>All agent definitions (agents are not uninstalled from hosts)</li>
            <li>Token usage history</li>
          </ul>
          <div className="flex gap-2">
            <Button trackingId="settings.danger-zone.confirm"
              variant="danger"
              size="sm"
              disabled={resetting}
              onClick={handleReset}
            >
              {resetting ? "Resetting..." : "Confirm Reset"}
            </Button>
            <Button trackingId="settings.danger-zone.cancel"
              variant="secondary"
              size="sm"
              onClick={() => setConfirmOpen(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {result ? (
        <p
          className={`mt-3 text-xs ${result.success ? "text-emerald-600" : "text-status-error"}`}
        >
          {result.message}
        </p>
      ) : null}
    </Card>
  );
}
