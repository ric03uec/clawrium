"use client";

import { PageHeader } from "@/components/layout";
import {
  AboutCard,
  TokenTrackingCard,
  GuiPreferencesCard,
  DangerZoneCard,
} from "@/components/settings";
import { useSettings, useVersion, useClearUsage } from "@/hooks";

export default function SettingsPage() {
  const { data: settings } = useSettings();
  const { data: version } = useVersion();
  const clearUsage = useClearUsage();

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Application configuration and preferences"
      />
      <div className="space-y-6">
        <AboutCard settings={settings} version={version} />
        <TokenTrackingCard
          settings={settings}
          onClear={() => clearUsage.mutate()}
        />
        <GuiPreferencesCard port={36000} />
        <DangerZoneCard />
      </div>
    </div>
  );
}
