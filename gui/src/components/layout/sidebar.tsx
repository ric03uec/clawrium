"use client";

import { GithubIcon } from "@/components/icons/github";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

interface NavItem {
  label: string;
  href: string;
}

const NAV_GROUPS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: "Main",
    items: [
      { label: "Dashboard", href: "/" },
      { label: "Agents", href: "/agents" },
      { label: "Hosts", href: "/hosts" },
    ],
  },
  {
    label: "Configuration",
    items: [
      { label: "Providers", href: "/providers" },
      { label: "Integrations", href: "/integrations" },
      { label: "MCP servers", href: "/mcp-servers" },
    ],
  },
];

const TRANSITIONAL_ITEMS: NavItem[] = [
  { label: "Topology", href: "/topology" },
  { label: "Skills", href: "/skills" },
];

const GITHUB_URL = "https://github.com/ric03uec/clawrium";

function isItemActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

function SettingsIcon({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06-.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function CollapseIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-4 w-4 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={collapsed ? "m9 18 6-6-6-6" : "m15 18-6-6 6-6"} />
    </svg>
  );
}

export function Sidebar({ version: sharedVersion }: { version?: string } = {}) {
  const pathname = usePathname();
  const [localVersion, setVersion] = useState<string | null>(null);
  const version = sharedVersion ?? localVersion;
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (sharedVersion !== undefined) return;
    const ctrl = new AbortController();
    fetch("/api/settings/version", { signal: ctrl.signal })
      .then((response) => response.json())
      .then((data) => setVersion(data.version || ""))
      .catch((error) => {
        if (error?.name !== "AbortError") setVersion("");
      });
    return () => ctrl.abort();
  }, [sharedVersion]);

  const linkRowClasses = (active: boolean) =>
    `block w-full text-left px-5 py-2.5 text-sm font-medium transition-colors ${
      active
        ? "text-primary-foreground border-l-[3px] border-primary bg-surface"
        : "text-secondary hover:text-primary-foreground hover:bg-panel border-l-[3px] border-transparent"
    }`;

  const settingsActive = isItemActive(pathname, "/settings");
  const toggleLabel = collapsed ? "Expand sidebar" : "Collapse sidebar";

  return (
    <aside
      aria-label="Fleet navigation"
      className={`app-sidebar bg-panel border-r border-default flex flex-col${collapsed ? " sidebar-collapsed" : ""}`}
    >
      <div className="app-sidebar-brand px-5 flex items-center">
        <div className="sidebar-brand-content inline-flex flex-col items-stretch">
          <Link
            href="/"
            className="flex items-center gap-2 font-semibold text-lg text-primary-text hover:text-primary-foreground transition-colors"
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- static export, no image optimizer */}
            <img
              src="/clawrium-logo.png"
              alt=""
              aria-hidden="true"
              className="h-8 w-8 object-contain shrink-0"
            />
            <span className="sidebar-brand-label">Clawrium</span>
          </Link>
          <p
            className="sidebar-brand-label text-xs font-medium text-primary-text"
            style={{ textAlign: "justify", textAlignLast: "justify" }}
          >
            Agent Fleet Manager
          </p>
        </div>
      </div>

      <nav aria-label="Main navigation" className="sidebar-primary-nav flex-1 mt-4">
        {NAV_GROUPS.map((group, groupIndex) => (
          <section key={group.label} aria-labelledby={`sidebar-group-${group.label.toLowerCase()}`}>
            <p
              id={`sidebar-group-${group.label.toLowerCase()}`}
              className={`px-5 text-xs uppercase text-muted ${groupIndex === 0 ? "pt-2" : "pt-4"}`}
            >
              {group.label}
            </p>
            {group.items.map((item) => {
              const active = isItemActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={linkRowClasses(active)}
                >
                  {item.label}
                </Link>
              );
            })}
          </section>
        ))}
      </nav>

      <nav aria-label="Transitional navigation" className="sidebar-transition-nav px-5 pb-4">
        <p className="pb-2 text-xs uppercase text-muted">Transitional pages</p>
        <div className="flex gap-3 text-xs">
          {TRANSITIONAL_ITEMS.map((item) => {
            const active = isItemActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={active ? "font-medium text-primary-foreground" : "text-secondary hover:text-primary-foreground"}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>

      <div className="sidebar-footer px-5 py-4 border-t border-default space-y-1">
        <Link
          href="/settings"
          aria-current={settingsActive ? "page" : undefined}
          title="Settings"
          className={`sidebar-footer-control flex items-center gap-2 px-1 py-1.5 text-sm rounded transition-colors ${
            settingsActive ? "text-primary-foreground font-medium" : "text-secondary hover:text-primary-foreground"
          }`}
        >
          <SettingsIcon className="h-4 w-4 shrink-0" />
          <span className="sidebar-footer-label">Settings</span>
        </Link>
        <a
          href={GITHUB_URL}
          target="_blank"
          rel="noreferrer noopener"
          title="GitHub"
          className="sidebar-footer-control flex items-center gap-2 px-1 py-1.5 text-sm text-secondary hover:text-primary-foreground transition-colors rounded"
        >
          <GithubIcon className="h-4 w-4 shrink-0" />
          <span className="sidebar-footer-label">GitHub</span>
        </a>
        <button
          type="button"
          className="sidebar-footer-control sidebar-toggle flex w-full items-center gap-2 px-1 py-1.5 text-sm text-secondary hover:text-primary-foreground rounded transition-colors"
          aria-label={toggleLabel}
          title={toggleLabel}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((current) => !current)}
        >
          <CollapseIcon collapsed={collapsed} />
          <span className="sidebar-footer-label">{toggleLabel}</span>
        </button>
        <div className="sidebar-version pt-2 border-t border-default">
          <span className="text-xs text-muted">{version ? `v${version}` : " "}</span>
        </div>
      </div>
    </aside>
  );
}
