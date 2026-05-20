"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { ExternalLinkRows } from "./external-links";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/" },
  { label: "Topology", href: "/topology" },
  { label: "Providers", href: "/providers" },
  { label: "Skills", href: "/skills" },
  { label: "Integrations", href: "/integrations" },
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
      <div className="px-5 py-6 border-b border-default">
        {/* inline-flex flex-col items-stretch shrink-wraps to the top-row
            width (logo + "Clawrium"), so the tagline below is bounded by
            that same width regardless of sidebar width. */}
        <div className="inline-flex flex-col items-stretch">
          <Link
            href="/"
            className="flex items-center gap-3 font-semibold text-2xl text-emerald-900 hover:text-emerald-950 transition-colors"
          >
            {/* Logo is decorative — accessible name is supplied by the
                wordmark <span> below. Without alt="" + aria-hidden, screen
                readers would announce "Clawrium" twice on this link. */}
            {/* eslint-disable-next-line @next/next/no-img-element -- static export, no image optimizer */}
            <img
              src="/clawrium-logo.png"
              alt=""
              aria-hidden="true"
              className="h-14 w-14 object-contain"
            />
            <span>Clawrium</span>
          </Link>
          {/* text-align: justify + text-align-last: justify stretches the
              line to fill the container width (which inline-flex+items-stretch
              fixes at the top row's width), so logo+Clawrium and the tagline
              share identical left/right edges. */}
          <p
            className="mt-2 text-base font-medium text-primary-text"
            style={{ textAlign: "justify", textAlignLast: "justify" }}
          >
            Agent Fleet Manager
          </p>
        </div>
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

      <div className="px-5 py-4 border-t border-default space-y-3">
        <ExternalLinkRows />
        <div className="pt-2 border-t border-default">
          <span className="text-xs text-muted">
            {version ? `v${version}` : " "}
          </span>
        </div>
      </div>
    </aside>
  );
}
