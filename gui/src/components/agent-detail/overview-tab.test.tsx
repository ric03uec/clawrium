import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { AgentDetail, AgentSkills } from "@/lib/types";

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
    latest_supported_version: "2026.5.28",
    ...overrides,
  } as AgentDetail;
}

describe("OverviewTab — upgrade-available badge", () => {
  beforeEach(() => {
    agentSkillsState.data = { installed: [], available: [] } as unknown as AgentSkills;
  });

  it("renders upgrade-available badge when latest_supported_version > agent.version", () => {
    render(<OverviewTab agent={makeAgent()} agentKey="demo" />);
    const badge = screen.getByTestId("upgrade-available-badge");
    expect(badge).toBeTruthy();
    expect(badge.textContent).toContain("2026.5.28");
    expect(badge.textContent).toContain("clawctl agent upgrade demo");
  });

  it("does not render badge when latest_supported_version equals agent.version", () => {
    render(
      <OverviewTab
        agent={makeAgent({
          version: "2026.5.28",
          latest_supported_version: "2026.5.28",
        })}
        agentKey="demo"
      />,
    );
    expect(screen.queryByTestId("upgrade-available-badge")).toBeNull();
  });

  it("does not render badge for version '?' sentinel (never-started agent)", () => {
    render(
      <OverviewTab
        agent={makeAgent({ version: "?", latest_supported_version: "2026.5.28" })}
        agentKey="demo"
      />,
    );
    expect(screen.queryByTestId("upgrade-available-badge")).toBeNull();
  });

  it("does not render badge when latest_supported_version is null", () => {
    render(
      <OverviewTab
        agent={makeAgent({ latest_supported_version: null })}
        agentKey="demo"
      />,
    );
    expect(screen.queryByTestId("upgrade-available-badge")).toBeNull();
  });
});
