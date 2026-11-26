"use client";

import { TabBar } from "@/design-system";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "chat", label: "Chat" },
  { id: "exec", label: "Exec" },
  { id: "configuration", label: "Configuration" },
  { id: "skills", label: "Skills" },
  { id: "memory", label: "Memory" },
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
