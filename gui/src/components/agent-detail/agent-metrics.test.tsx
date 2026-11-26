import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentDetail, AgentDetailHealth } from "@/lib/types";

// useUsageByAgent is the only hook the component uses. Return an empty
// dataset so we can assert the metric-cell content unambiguously.
vi.mock("@/hooks", () => ({
  useUsageByAgent: () => ({ data: [] }),
}));

import { AgentMetrics } from "./agent-metrics";

function makeAgent(overrides: Partial<AgentDetail> = {}): AgentDetail {
  return {
    agent_key: "demo",
    agent_name: "demo",
    agent_type: "openclaw",
    host: "192.168.1.100",
    host_alias: "box",
    host_os_family: "linux",
    status: "checking",
    model: "-",
    uptime: "2h",
    gateway_url: null,
    provider: "",
    provider_type: "",
    addresses: [],
    version: "2026.4.2",
    device_id: "",
    onboarding_step: "ready",
    gateway_port: null,
    ...overrides,
  } as AgentDetail;
}

function makeHealth(
  overrides: Partial<AgentDetailHealth> = {},
): AgentDetailHealth {
  return {
    agent_key: "demo",
    status: "running",
    process_running: true,
    health_error: null,
    cpu_count: 4,
    memory_total_mb: 8192,
    missing_secrets: null,
    onboarding_step: "ready",
    latest_supported_version: "2026.5.28",
    ...overrides,
  };
}

describe("AgentMetrics — health loading fallback (#758 ATX W7)", () => {
  it("renders 'checking' status from static fallback when health is undefined", () => {
    render(<AgentMetrics agent={makeAgent()} health={undefined} />);
    const status = screen.getByText("Checking");
    expect(status).toHaveAttribute("data-status", "checking");
  });

  it("renders live status from health once the probe resolves", () => {
    render(<AgentMetrics agent={makeAgent()} health={makeHealth()} />);
    const status = screen.getByText("Running");
    expect(status).toHaveAttribute("data-status", "running");
  });

  it("renders uptime from the static endpoint regardless of health state", () => {
    // #758 S5: uptime is owned by useAgent, never duplicated in /health.
    render(<AgentMetrics agent={makeAgent()} health={undefined} />);
    expect(screen.getByText("2h")).toBeTruthy();
  });

  it("renders '—' for uptime when neither static nor health carry one", () => {
    render(
      <AgentMetrics agent={makeAgent({ uptime: "" })} health={undefined} />,
    );
    const uptimeCell = document.querySelector('[data-i7n-name="agent-detail.metrics.uptime"]');
    expect(uptimeCell).toHaveTextContent("—");
    expect(uptimeCell).toHaveTextContent("Uptime");
  });
});
