"use client";

/**
 * Clawrium-owned application-shell primitive.
 *
 * This component is intentionally kept in the design-system registry so
 * application code supplies navigation data instead of recreating sidebar
 * markup, collapse behavior, or styling.
 */
import type {
  AnchorHTMLAttributes,
  ImgHTMLAttributes,
  ReactNode,
} from "react";
import { useState } from "react";
import { cn } from "@/lib/utils";

export interface AppSidebarLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string;
}

export interface AppSidebarNavItem {
  label: string;
  description: string;
  href: string;
  icon: ReactNode;
  active?: boolean;
}

export interface AppSidebarNavGroup {
  label: string;
  items: AppSidebarNavItem[];
}

export interface AppSidebarAction {
  label: string;
  href: string;
  icon: ReactNode;
  active?: boolean;
  external?: boolean;
}

export interface AppSidebarProps {
  trackingId: string;
  ariaLabel: string;
  brand: {
    label: string;
    subtitle: string;
    href: string;
    logoSrc: string;
    logoProps?: Omit<ImgHTMLAttributes<HTMLImageElement>, "src">;
  };
  groups: AppSidebarNavGroup[];
  actions: AppSidebarAction[];
  version?: string | null;
  renderLink?: (props: AppSidebarLinkProps) => ReactNode;
  collapseIcons: { expanded: ReactNode; collapsed: ReactNode };
  className?: string;
}

export function AppSidebar({
  trackingId,
  ariaLabel,
  brand,
  groups,
  actions,
  version,
  renderLink,
  collapseIcons,
  className,
}: AppSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const toggleLabel = collapsed ? "Expand sidebar" : "Collapse sidebar";
  const SidebarLink = (props: AppSidebarLinkProps) =>
    renderLink ? <>{renderLink(props)}</> : <a {...props} />;

  return (
    <aside
      aria-label={ariaLabel}
      className={cn("ds-app-sidebar", collapsed && "sidebar-collapsed", className)}
      data-collapsed={collapsed}
      data-i7n-component="app-sidebar"
      data-i7n-name={trackingId}
    >
      <SidebarLink
        href={brand.href}
        className="ds-app-sidebar-brand"
        aria-label={brand.label}
        title={`${brand.label} — ${brand.subtitle}`}
      >
        {/* Portable static asset: optimization belongs to the consuming app. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          {...brand.logoProps}
          src={brand.logoSrc}
          alt=""
          aria-hidden="true"
          className={cn("ds-app-sidebar-logo", brand.logoProps?.className)}
        />
        <span className="ds-app-sidebar-brand-text">
          <span className="ds-app-sidebar-brand-title">{brand.label}</span>
          <span className="ds-app-sidebar-brand-subtitle">{brand.subtitle}</span>
        </span>
      </SidebarLink>

      <nav aria-label="Main navigation" className="ds-app-sidebar-nav">
        {groups.map((group) => (
          <section key={group.label} aria-labelledby={`${trackingId}-${group.label.toLowerCase().replaceAll(" ", "-")}`}>
            <p
              id={`${trackingId}-${group.label.toLowerCase().replaceAll(" ", "-")}`}
              className="ds-app-sidebar-section"
            >
              {group.label}
            </p>
            <div className="ds-app-sidebar-group">
              {group.items.map((item) => (
                <SidebarLink
                  key={item.href}
                  href={item.href}
                  aria-label={item.label}
                  aria-current={item.active ? "page" : undefined}
                  className="ds-app-sidebar-card"
                  data-active={item.active || undefined}
                  title={item.label}
                >
                  <span className="ds-app-sidebar-card-tile" aria-hidden="true">{item.icon}</span>
                  <span className="ds-app-sidebar-card-text">
                    <span className="ds-app-sidebar-card-title">{item.label}</span>
                    <span className="ds-app-sidebar-card-subtitle">{item.description}</span>
                  </span>
                </SidebarLink>
              ))}
            </div>
          </section>
        ))}
      </nav>

      <div className="ds-app-sidebar-footer">
        {actions.map((action) => (
          <SidebarLink
            key={action.href}
            href={action.href}
            aria-label={action.label}
            aria-current={action.active ? "page" : undefined}
            title={action.label}
            className="ds-app-sidebar-action"
            data-active={action.active || undefined}
            {...(action.external ? { target: "_blank", rel: "noreferrer noopener" } : {})}
          >
            {action.icon}
            <span className="ds-app-sidebar-action-label">{action.label}</span>
          </SidebarLink>
        ))}
        <button
          type="button"
          className="ds-app-sidebar-action"
          aria-label={toggleLabel}
          title={toggleLabel}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((current) => !current)}
        >
          {collapsed ? collapseIcons.collapsed : collapseIcons.expanded}
          <span className="ds-app-sidebar-action-label">{toggleLabel}</span>
        </button>
        <div className="ds-app-sidebar-version">
          <span>{version ? `v${version}` : " "}</span>
        </div>
      </div>
    </aside>
  );
}
