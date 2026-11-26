import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AgentStatus } from "@/lib/types";
import { AGENT_STATUS_PRESENTATION, StatusDot } from "./status-dot";

const STATUSES: AgentStatus[] = [
  "running",
  "stopped",
  "degraded",
  "not_installed",
  "pending_onboard",
  "onboarding",
  "ready",
  "checking",
  "install_missing",
  "unknown",
];

describe("StatusDot compatibility wrapper", () => {
  it("covers every AgentStatus through StatusLight", () => {
    const { container } = render(
      <>{STATUSES.map((status) => <StatusDot key={status} status={status} />)}</>,
    );

    for (const status of STATUSES) {
      const dot = container.querySelector(`[data-status="${status}"]`);
      expect(dot).toHaveAttribute("data-i7n-component", "status-light");
      expect(dot).toHaveAttribute("data-light", AGENT_STATUS_PRESENTATION[status].tone);
    }
  });

  it("retains pulse semantics for running and checking only", () => {
    const { container } = render(
      <>
        <StatusDot status="running" />
        <StatusDot status="checking" />
        <StatusDot status="install_missing" />
        <StatusDot status="unknown" />
      </>,
    );
    expect(container.querySelector('[data-status="running"]')).toHaveClass("animate-pulse");
    expect(container.querySelector('[data-status="checking"]')).toHaveClass("animate-pulse");
    expect(container.querySelector('[data-status="install_missing"]')).not.toHaveClass("animate-pulse");
    expect(container.querySelector('[data-status="unknown"]')).not.toHaveClass("animate-pulse");
  });
});
