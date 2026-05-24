"use client";

import { Card } from "@/components/ui";

interface GuiPreferencesCardProps {
  port: number;
}

export function GuiPreferencesCard({ port }: GuiPreferencesCardProps) {
  return (
    <Card>
      <h2 className="text-lg font-semibold text-primary mb-4">
        GUI Preferences
      </h2>
      <div className="grid grid-cols-[140px_1fr] gap-y-3 text-sm">
        <span className="text-muted">Port</span>
        <span className="font-mono">{port}</span>

        <span className="text-muted">Auto-open</span>
        <span>Opens browser on launch</span>

        <span className="text-muted">Refresh Rate</span>
        <span>15s (fleet status polling)</span>
      </div>
      <p className="mt-4 text-xs text-muted">
        Configure via CLI flags:{" "}
        <code className="bg-surface px-1 py-0.5 rounded text-xs">
          clawctl gui --port 36000 --no-open
        </code>
      </p>
    </Card>
  );
}
