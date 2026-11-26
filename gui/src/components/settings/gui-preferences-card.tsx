"use client";

import { Card } from "@/design-system";

interface GuiPreferencesCardProps {
  port: number;
}

export function GuiPreferencesCard({ port }: GuiPreferencesCardProps) {
  return (
    <Card trackingId="settings.gui-preferences.card">
      <h2 className="text-lg font-semibold text-primary-foreground mb-4">
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
        These values are set at launch time. Restart the GUI to apply changes.
      </p>
    </Card>
  );
}
