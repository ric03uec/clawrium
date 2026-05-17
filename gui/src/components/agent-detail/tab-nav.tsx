"use client";

const TABS = [
  { id: "chat", label: "Chat" },
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
    <div className="border-b border-default">
      <nav className="flex gap-0" aria-label="Agent detail tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              active === tab.id
                ? "border-primary text-primary"
                : "border-transparent text-muted hover:text-secondary hover:border-gray-300"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
