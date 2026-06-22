"use client";

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

  if (!src) {
    return (
      <div
        aria-label={`${type} icon`}
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
      alt={`${type} logo`}
      width={size}
      height={size}
      className={className}
      loading="lazy"
    />
  );
}
