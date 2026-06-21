import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentDetail, AgentDetailHealth } from "@/lib/types";

const webUIState = { data: undefined, isLoading: false, isError: false };
const noopMutation = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };

vi.mock("@/hooks", () => ({
  PAIRING_AGENT_TYPES: new Set(["zeroclaw"]),
  TOKEN_REVEAL_AGENT_TYPES: new Set(["openclaw"]),
  useAgentActions: () => ({
    start: noopMutation,
    stop: noopMutation,
    restart: noopMutation,
  }),
  useAgentConnectionToken: () => ({ ...noopMutation, data: undefined, isError: false, error: null }),
  useAgentPairingCode: () => ({ ...noopMutation, data: undefined, isError: false, error: null }),
  useAgentWebUI: () => webUIState,
}));

import { AgentHeader } from "./agent-header";

function makeAgent(overrides: Partial<AgentDetail> = {}): AgentDetail {
  return {
    agent_key: "demo",
    agent_name: "demo",
    agent_type: "hermes",
    host: "192.168.1.100",
    host_alias: "box",
    host_os_family: "linux",
    status: "checking",
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
    process_running: true,
    health_error: null,
    cpu_count: 4,
    memory_total_mb: 8192,
    missing_secrets: null,
    onboarding_step: "ready",
    latest_supported_version: null,
    ...overrides,
  };
}

describe("AgentHeader — health loading fallback (#758 ATX W7)", () => {
  it("renders agent identity even when health is undefined", () => {
    render(<AgentHeader agent={makeAgent()} health={undefined} />);
    expect(screen.getByText("demo")).toBeTruthy();
    // Type + version chip is one of the few places the header renders
    // the agent_type — its presence confirms the chrome painted.
    expect(screen.getByText(/hermes v2026\.4\.2/)).toBeTruthy();
  });

  it("hides Start/Stop/Restart while health is undefined", () => {
    // liveStatus falls back to agent.status === "checking" so isRunning
    // and isStopped are both false — neither branch should render the
    // lifecycle buttons.
    render(<AgentHeader agent={makeAgent()} health={undefined} />);
    expect(screen.queryByText("Start")).toBeNull();
    expect(screen.queryByText("Stop")).toBeNull();
    expect(screen.queryByText("Restart")).toBeNull();
  });

  it("shows Start when health reports stopped", () => {
    render(
      <AgentHeader
        agent={makeAgent()}
        health={makeHealth({ status: "stopped" })}
      />,
    );
    expect(screen.getByText("Start")).toBeTruthy();
    expect(screen.queryByText("Stop")).toBeNull();
  });

  it("shows Stop+Restart when health reports running", () => {
    render(<AgentHeader agent={makeAgent()} health={makeHealth()} />);
    expect(screen.getByText("Stop")).toBeTruthy();
    expect(screen.getByText("Restart")).toBeTruthy();
    expect(screen.queryByText("Start")).toBeNull();
  });
});
