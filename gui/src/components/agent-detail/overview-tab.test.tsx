import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { AgentDetail, AgentDetailHealth, AgentSkills } from "@/lib/types";

const agentSkillsState: {
  data: AgentSkills | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
} = { data: undefined, isLoading: false, error: null, refetch: vi.fn() };

vi.mock("@/hooks", () => ({
  useAgentSkills: () => agentSkillsState,
}));

import { OverviewTab } from "./overview-tab";

function makeAgent(overrides: Partial<AgentDetail> = {}): AgentDetail {
  return {
    agent_key: "demo",
    agent_name: "demo",
    agent_type: "openclaw",
    host: "192.168.1.100",
    host_alias: "box",
    host_os_family: "linux",
    status: "running",
    model: "-",
    uptime: "1m",
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
    uptime: "1m",
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

describe("OverviewTab — upgrade-available badge", () => {
  beforeEach(() => {
    agentSkillsState.data = { installed: [], available: [] } as unknown as AgentSkills;
  });

  it("renders upgrade-available badge when latest_supported_version > agent.version", () => {
    render(
      <OverviewTab agent={makeAgent()} agentKey="demo" health={makeHealth()} />,
    );
    const badge = screen.getByTestId("upgrade-available-badge");
    expect(badge).toBeTruthy();
    expect(badge.textContent).toContain("2026.5.28");
    expect(badge.textContent).toContain("clawctl agent upgrade demo");
  });

  it("does not render badge when latest_supported_version equals agent.version", () => {
    render(
      <OverviewTab
        agent={makeAgent({ version: "2026.5.28" })}
        agentKey="demo"
        health={makeHealth({ latest_supported_version: "2026.5.28" })}
      />,
    );
    expect(screen.queryByTestId("upgrade-available-badge")).toBeNull();
  });

  it("does not render badge for version '?' sentinel (never-started agent)", () => {
    render(
      <OverviewTab
        agent={makeAgent({ version: "?" })}
        agentKey="demo"
        health={makeHealth({ latest_supported_version: "2026.5.28" })}
      />,
    );
    expect(screen.queryByTestId("upgrade-available-badge")).toBeNull();
  });

  it("does not render badge when latest_supported_version is null", () => {
    render(
      <OverviewTab
        agent={makeAgent()}
        agentKey="demo"
        health={makeHealth({ latest_supported_version: null })}
      />,
    );
    expect(screen.queryByTestId("upgrade-available-badge")).toBeNull();
  });

  it("does not render badge while health is still loading (#758)", () => {
    // Health undefined → latest_supported_version unknown → never show
    // an upgrade badge with the wrong version.
    render(
      <OverviewTab agent={makeAgent()} agentKey="demo" health={undefined} />,
    );
    expect(screen.queryByTestId("upgrade-available-badge")).toBeNull();
  });

  it("renders 'Checking for upgrades…' while health is loading (#758 W3)", () => {
    // The loading affordance distinguishes "registry lookup in flight"
    // from "confirmed no upgrade" — without it, an outdated agent
    // would silently look up-to-date during the loading window.
    render(
      <OverviewTab agent={makeAgent()} agentKey="demo" health={undefined} />,
    );
    expect(screen.getByTestId("upgrade-loading-badge")).toBeTruthy();
  });

  it("hides the loading affordance once health resolves with null", () => {
    render(
      <OverviewTab
        agent={makeAgent()}
        agentKey="demo"
        health={makeHealth({ latest_supported_version: null })}
      />,
    );
    expect(screen.queryByTestId("upgrade-loading-badge")).toBeNull();
    expect(screen.queryByTestId("upgrade-available-badge")).toBeNull();
  });
});
