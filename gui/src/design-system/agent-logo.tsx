/**
 * @source i7n-ui/src/design-system/agent-logo.tsx
 * @deps @/lib/utils
 * @tracking-component agent-logo
 */
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const AGENT_LOGOS: Record<string, string> = {
  claude: "/agents/claude.svg",
  "claude-code": "/agents/claude.svg",
  codex: "/agents/openai.svg",
  ethos: "/agents/ethos.svg",
  hermes: "/agents/hermes.svg",
  openclaw: "/agents/openclaw.svg",
  pi: "/agents/pi.svg",
  zeroclaw: "/agents/zeroclaw.svg",
  opencode: "/agents/opencode.svg",
  cursor: "/agents/cursor.svg",
  warp: "/agents/warp.svg",
  herdr: "/agents/herdr.png",
};

export interface AgentLogoProps extends HTMLAttributes<HTMLElement> {
  kind: string;
  size?: number;
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

export function AgentLogo({ kind, size = 16, className, trackingId, ...props }: AgentLogoProps) {
  const src = AGENT_LOGOS[kind.toLowerCase()];
  if (!src) {
    return (
      <span
        className={cn("ds-agent-logo-glyph", className)}
        data-i7n-component="agent-logo"
        data-i7n-name={trackingId}
        data-kind={kind}
        style={{ width: size, height: size, fontSize: size * 0.68 }}
        aria-label={kind}
        {...props}
      >
        {kind === "pi" ? "π" : kind.charAt(0).toUpperCase()}
      </span>
    );
  }
  return (
    // Keep the copied primitive's fixed-size public asset behavior; optimization
    // belongs at the consuming app boundary rather than in this portable fork.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className={className}
      data-i7n-component="agent-logo"
      data-i7n-name={trackingId}
      data-kind={kind}
      src={src}
      alt={kind}
      width={size}
      height={size}
      style={{ display: "block" }}
    />
  );
}
