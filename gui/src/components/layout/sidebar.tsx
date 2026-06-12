"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { ExternalLinkRows } from "./external-links";

interface NavItem {
  label: string;
  href: string;
  disabled?: boolean;
  upvoteUrl?: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/" },
  { label: "Agents", href: "/agents" },
  { label: "Topology", href: "/topology" },
  { label: "Providers", href: "/providers" },
  { label: "Skills", href: "/skills" },
  { label: "Integrations", href: "/integrations" },
  {
    label: "MCPs",
    href: "/mcps",
    disabled: true,
    upvoteUrl: "https://github.com/ric03uec/clawrium/issues/698",
  },
  {
    label: "Scheduled Jobs",
    href: "/scheduled-jobs",
    disabled: true,
    upvoteUrl: "https://github.com/ric03uec/clawrium/issues/699",
  },
  {
    label: "Agent Builder",
    href: "/agent-builder",
    disabled: true,
    upvoteUrl: "https://github.com/ric03uec/clawrium/issues/700",
  },
  { label: "Settings", href: "/settings" },
];

const COMING_SOON_TOOLTIP =
  "Coming soon — this feature is on our roadmap. Upvote on GitHub to bump priority.";

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
          const isActive = !item.disabled && isItemActive(pathname, item.href);

          if (item.disabled) {
            return (
              <div
                key={item.href}
                className="flex items-center justify-between gap-2 px-5 py-2.5 text-sm font-medium border-l-[3px] border-transparent"
              >
                <span className="flex items-center gap-1.5 text-muted cursor-default">
                  {item.label}
                  <button
                    type="button"
                    title={COMING_SOON_TOOLTIP}
                    aria-label={`${item.label} — coming soon (more info)`}
                    className="inline-flex items-center justify-center h-4 w-4 rounded-full text-muted hover:text-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 16 16"
                      className="h-3.5 w-3.5"
                      fill="currentColor"
                    >
                      <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm0 12.5A5.5 5.5 0 118 2.5a5.5 5.5 0 010 11zM7.25 7h1.5v5h-1.5V7zM8 4.25a.9.9 0 110 1.8.9.9 0 010-1.8z" />
                    </svg>
                  </button>
                </span>
                {item.upvoteUrl && (
                  <a
                    href={item.upvoteUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    aria-label={`Upvote ${item.label} on GitHub`}
                    className="inline-flex items-center gap-0.5 text-xs font-medium text-secondary hover:text-primary hover:underline transition-colors"
                  >
                    Upvote
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 12 12"
                      className="h-2.5 w-2.5"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M3 9l6-6M5 3h4v4" />
                    </svg>
                  </a>
                )}
              </div>
            );
          }

          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={`
                block px-5 py-2.5 text-sm font-medium transition-colors
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
            {version ? `v${version}` : " "}
          </span>
        </div>
      </div>
    </aside>
  );
}
