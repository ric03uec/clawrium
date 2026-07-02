"use client";

// #834: slack-user and slack-cookie both map to the same Slack icon
// (they are one workspace with two auth flows). The SVG asset itself
// is a Phase 4 (docs/branding) follow-up — the fallback badge in this
// component renders `SL` from the type string, which is acceptable for
// the driver slice.
const ICON_PATHS: Record<string, string> = {
  github: "/integration-icons/github.svg",
  gitlab: "/integration-icons/gitlab.svg",
  atlassian: "/integration-icons/atlassian.svg",
  linear: "/integration-icons/linear.svg",
  notion: "/integration-icons/notion.svg",
  brave: "/integration-icons/brave.svg",
  git: "/integration-icons/git.svg",
};

interface IntegrationIconProps {
  type: string;
  size?: number;
  className?: string;
}

export function IntegrationIcon({
  type,
  size = 24,
  className,
}: IntegrationIconProps) {
  const src = ICON_PATHS[type];

  // The icon is decorative: every call site renders the integration's
  // type label next to it (see integration-card.tsx). Mark both branches
  // as `aria-hidden` so screen readers do not read the type twice.
  if (!src) {
    return (
      <div
        data-testid="integration-icon-fallback"
        aria-hidden="true"
        className={`flex items-center justify-center rounded-md bg-slate-100 text-slate-600 text-[10px] font-semibold uppercase ${className ?? ""}`}
        style={{ width: size, height: size }}
      >
        {type.slice(0, 2)}
      </div>
    );
  }

  return (
    // Static SVG assets served from /public; next/image gives no benefit
    // under `output: export` with `images.unoptimized = true`.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      className={className}
      loading="lazy"
    />
  );
}
