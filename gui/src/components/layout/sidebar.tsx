"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/" },
  { label: "Topology", href: "/topology" },
  { label: "Providers", href: "/providers" },
  { label: "Settings", href: "/settings" },
];

function isItemActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

export function Sidebar() {
  const pathname = usePathname();
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/settings/version", { signal: ctrl.signal })
      .then((r) => r.json())
      .then((data) => setVersion(data.version || ""))
      .catch((err) => {
        if (err?.name !== "AbortError") setVersion("");
      });
    return () => ctrl.abort();
  }, []);

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-sidebar bg-panel border-r border-default flex flex-col">
      <div className="px-5 py-5">
        <Link
          href="/"
          className="flex items-center gap-2 text-primary font-semibold text-lg"
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- static export, no image optimizer */}
          <img
            src="/clawrium-logo.png"
            alt="Clawrium"
            className="h-7 w-7 object-contain"
          />
          <span>CLM</span>
        </Link>
      </div>

      <nav aria-label="Main navigation" className="flex-1 mt-4">
        {NAV_ITEMS.map((item) => {
          const isActive = isItemActive(pathname, item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={`
                block px-5 py-3 text-sm font-medium transition-colors
                ${
                  isActive
                    ? "text-primary border-l-[3px] border-primary bg-surface"
                    : "text-secondary hover:text-primary hover:bg-panel border-l-[3px] border-transparent"
                }
              `}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="px-5 py-4 border-t border-default">
        <span className="text-xs text-muted">
          {version ? `v${version}` : " "}
        </span>
      </div>
    </aside>
  );
}
