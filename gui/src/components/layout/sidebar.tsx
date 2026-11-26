"use client";

import { GithubIcon } from "@/components/icons/github";
import {
  AppSidebar,
  type AppSidebarNavGroup,
} from "@/design-system";
import {
  Bot,
  Boxes,
  Cable,
  LayoutDashboard,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Server,
  Settings,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const GITHUB_URL = "https://github.com/ric03uec/clawrium";

function isItemActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

export function Sidebar({ version: sharedVersion }: { version?: string } = {}) {
  const pathname = usePathname();
  const [localVersion, setVersion] = useState<string | null>(null);
  const version = sharedVersion ?? localVersion;

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

  const groups: AppSidebarNavGroup[] = [
    {
      label: "Main",
      items: [
        { label: "Dashboard", description: "Fleet overview", href: "/", icon: <LayoutDashboard size={17} />, active: isItemActive(pathname, "/") },
        { label: "Agents", description: "Manage agent instances", href: "/agents", icon: <Bot size={17} />, active: isItemActive(pathname, "/agents") },
        { label: "Hosts", description: "Machines in your fleet", href: "/hosts", icon: <Server size={17} />, active: isItemActive(pathname, "/hosts") },
      ],
    },
    {
      label: "Configuration",
      items: [
        { label: "Providers", description: "Models and credentials", href: "/providers", icon: <Plug size={17} />, active: isItemActive(pathname, "/providers") },
        { label: "Integrations", description: "External services", href: "/integrations", icon: <Cable size={17} />, active: isItemActive(pathname, "/integrations") },
        { label: "MCP servers", description: "Tool server connections", href: "/mcp-servers", icon: <Boxes size={17} />, active: isItemActive(pathname, "/mcp-servers") },
      ],
    },
  ];

  return (
    <AppSidebar
      trackingId="shell.sidebar.navigation"
      ariaLabel="Fleet navigation"
      renderLink={(props) => <Link {...props} />}
      brand={{
        label: "Clawrium",
        subtitle: "Agent Fleet Manager",
        href: "/",
        logoSrc: "/clawrium-logo.png",
      }}
      groups={groups}
      actions={[
        {
          label: "Settings",
          href: "/settings",
          icon: <Settings size={17} aria-hidden="true" />,
          active: isItemActive(pathname, "/settings"),
        },
        {
          label: "GitHub",
          href: GITHUB_URL,
          icon: <GithubIcon className="h-[17px] w-[17px] shrink-0" />,
          external: true,
        },
      ]}
      collapseIcons={{
        expanded: <PanelLeftClose size={17} aria-hidden="true" />,
        collapsed: <PanelLeftOpen size={17} aria-hidden="true" />,
      }}
      version={version}
    />
  );
}
