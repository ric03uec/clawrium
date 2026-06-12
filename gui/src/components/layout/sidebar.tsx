"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ExternalLinkRows } from "./external-links";
import { ComingSoonModal } from "./coming-soon-modal";

interface NavLinkItem {
  kind: "link";
  label: string;
  href: string;
}

interface NavStubItem {
  kind: "stub";
  label: string;
  body: string;
  upvoteUrl: string;
}

type NavItem = NavLinkItem | NavStubItem;

const NAV_ITEMS: NavItem[] = [
  { kind: "link", label: "Dashboard", href: "/" },
  { kind: "link", label: "Agents", href: "/agents" },
  { kind: "link", label: "Topology", href: "/topology" },
  { kind: "link", label: "Providers", href: "/providers" },
  { kind: "link", label: "Skills", href: "/skills" },
  { kind: "link", label: "Integrations", href: "/integrations" },
  {
    kind: "stub",
    label: "MCPs",
    body: "MCP (Model Context Protocol) support isn't available in Clawrium yet. It's on the roadmap — your upvote on GitHub helps us prioritize.",
    upvoteUrl: "https://github.com/ric03uec/clawrium/issues/698",
  },
  {
    kind: "stub",
    label: "Scheduled Jobs",
    body: "Scheduling recurring or one-off agent commands isn't available yet. It's on the roadmap — your upvote on GitHub helps us prioritize.",
    upvoteUrl: "https://github.com/ric03uec/clawrium/issues/699",
  },
  {
    kind: "stub",
    label: "Agent Builder",
    body: "A visual editor for new agent definitions isn't available yet. It's on the roadmap — your upvote on GitHub helps us prioritize.",
    upvoteUrl: "https://github.com/ric03uec/clawrium/issues/700",
  },
];

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
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [version, setVersion] = useState<string | null>(null);
  const [openStub, setOpenStub] = useState<NavStubItem | null>(null);
  // Holds the button that opened the modal, so we can return focus to it
  // when the modal closes (WCAG 2.4.3 — keyboard users would otherwise
  // drop to <body> and lose their place in the nav).
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const closeStub = useCallback(() => {
    // Capture the trigger before clearing state so subsequent renders
    // can't race the ref. focus() is safe to call synchronously: by the
    // time the dialog's 'close' event fires, the browser has already
    // released focus to <body>.
    const trigger = triggerRef.current;
    setOpenStub(null);
    if (trigger) trigger.focus();
  }, []);

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

  const linkRowClasses = (active: boolean) =>
    `block w-full text-left px-5 py-2.5 text-sm font-medium transition-colors ${
      active
        ? "text-primary border-l-[3px] border-primary bg-surface"
        : "text-secondary hover:text-primary hover:bg-panel border-l-[3px] border-transparent"
    }`;

  // Stub rows are intentionally grayed: text-muted resting, hover lifts to
  // text-secondary so the click affordance still reads. No left bar — they
  // never represent an "active page."
  const stubRowClasses =
    "block w-full text-left px-5 py-2.5 text-sm font-medium text-muted hover:text-secondary hover:bg-panel transition-colors border-l-[3px] border-transparent";

  const settingsActive = isItemActive(pathname, "/settings");

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
          if (item.kind === "stub") {
            return (
              <button
                key={item.label}
                type="button"
                aria-label={`${item.label} — coming soon`}
                onClick={(e) => {
                  triggerRef.current = e.currentTarget;
                  setOpenStub(item);
                }}
                className={stubRowClasses}
              >
                {item.label}
              </button>
            );
          }

          const isActive = isItemActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={linkRowClasses(isActive)}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="px-5 py-4 border-t border-default space-y-3">
        <ul className="space-y-1">
          <li>
            <Link
              href="/settings"
              aria-current={settingsActive ? "page" : undefined}
              className={`flex items-center gap-2 px-1 py-1.5 text-sm rounded transition-colors ${
                settingsActive
                  ? "text-primary font-medium"
                  : "text-secondary hover:text-primary"
              }`}
            >
              <SettingsIcon className="h-4 w-4" />
              <span>Settings</span>
            </Link>
          </li>
        </ul>
        <ExternalLinkRows />
        <div className="pt-2 border-t border-default">
          <span className="text-xs text-muted">
            {version ? `v${version}` : " "}
          </span>
        </div>
      </div>

      <ComingSoonModal
        open={openStub !== null}
        onClose={closeStub}
        featureName={openStub?.label ?? ""}
        body={openStub?.body ?? ""}
        upvoteUrl={openStub?.upvoteUrl ?? ""}
      />
    </aside>
  );
}
