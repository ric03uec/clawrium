"use client";

import { TabBar } from "@/design-system";

// #1071 phase 6: Chat / Exec / Memory tabs removed with their backing
// subsystems. Operators SSH to the host for interactive sessions.
const TABS = [
  { id: "overview", label: "Overview" },
  { id: "configuration", label: "Configuration" },
  { id: "logs", label: "Logs" },
] as const;

export type TabId = (typeof TABS)[number]["id"];

interface TabNavProps {
  active: TabId;
  onChange: (tab: TabId) => void;
}

export function TabNav({ active, onChange }: TabNavProps) {
  return (
    <TabBar
      trackingId="agent-detail.page.tabs"
      aria-label="Agent detail tabs"
      tabs={TABS.map((tab) => ({ ...tab }))}
      value={active}
      onValueChange={(tab) => onChange(tab as TabId)}
    />
  );
}
