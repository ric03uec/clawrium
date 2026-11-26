/**
 * @source i7n-ui/src/design-system/tab-bar.tsx
 * @deps @/lib/utils
 * @tracking-component tab-bar
 */
"use client";

import { useRef, type HTMLAttributes, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface TabBarProps extends Omit<HTMLAttributes<HTMLDivElement>, "onChange"> {
  tabs: { id: string; label: ReactNode }[];
  value: string;
  onValueChange: (id: string) => void;
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

function stableTabPart(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/g, "-");
}

export function getTabId(trackingId: string, tabId: string): string {
  return `${stableTabPart(trackingId)}-tab-${stableTabPart(tabId)}`;
}

export function getTabPanelId(trackingId: string, tabId: string): string {
  return `${stableTabPart(trackingId)}-panel-${stableTabPart(tabId)}`;
}

export function TabBar({ tabs, value, onValueChange, className, trackingId, ...props }: TabBarProps) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectedIndex = Math.max(0, tabs.findIndex((tab) => tab.id === value));

  function selectAndFocus(index: number) {
    const tab = tabs[index];
    if (!tab) return;
    onValueChange(tab.id);
    tabRefs.current[index]?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | undefined;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === undefined) return;
    event.preventDefault();
    selectAndFocus(nextIndex);
  }

  return (
    <div
      className={cn("ds-tab-bar", className)}
      role="tablist"
      data-i7n-component="tab-bar"
      data-i7n-name={trackingId}
      {...props}
    >
      {tabs.map(({ id, label }, index) => {
        const isSelected = index === selectedIndex;
        return (
          <button
            key={id}
            ref={(element) => { tabRefs.current[index] = element; }}
            id={getTabId(trackingId, id)}
            type="button"
            role="tab"
            className="ds-tab-btn"
            data-active={isSelected}
            data-i7n-name={`${trackingId}.tab.${id}`}
            aria-selected={isSelected}
            aria-controls={getTabPanelId(trackingId, id)}
            tabIndex={isSelected ? 0 : -1}
            onClick={() => onValueChange(id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
