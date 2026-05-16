import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/components/ui/modal", () => ({
  Modal: ({
    open,
    children,
    footer,
    title,
  }: {
    open: boolean;
    children: React.ReactNode;
    footer?: React.ReactNode;
    title: string;
  }) =>
    open ? (
      <div role="dialog" aria-label={title}>
        <h2>{title}</h2>
        {children}
        <div>{footer}</div>
      </div>
    ) : null,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    onClick,
  }: {
    children: React.ReactNode;
    onClick?: () => void;
  }) => <button onClick={onClick}>{children}</button>,
}));

vi.mock("@/components/ui/status-dot", () => ({
  StatusDot: ({ status }: { status: string }) => (
    <span data-testid="status-dot" data-status={status} />
  ),
}));

import { AgentInfoModal } from "./agent-info-modal";
import { type TopologyAgent } from "@/lib/types";

function makeAgent(overrides: Partial<TopologyAgent> = {}): TopologyAgent {
  return {
    agent_key: "espresso",
    agent_name: "espresso",
    agent_type: "hermes",
    status: "running",
    model: "qwen3-coder:30b-128k",
    version: "1.0.0",
    uptime: "1m",
    provider: "local-inx",
    provider_type: "ollama",
    provider_endpoint: "http://192.168.1.17:11434",
    ...overrides,
  };
}

describe("AgentInfoModal", () => {
  it("renders the Provider Endpoint row when endpoint is set", () => {
    render(
      <AgentInfoModal
        agent={makeAgent()}
        hostAlias="wolf-i"
        onClose={() => {}}
      />
    );
    expect(screen.getByText("Provider Endpoint")).toBeInTheDocument();
    expect(screen.getByText("http://192.168.1.17:11434")).toBeInTheDocument();
  });

  it("omits the Provider Endpoint row when endpoint is null", () => {
    render(
      <AgentInfoModal
        agent={makeAgent({ provider_endpoint: null, provider_type: "bedrock" })}
        hostAlias="wolf-i"
        onClose={() => {}}
      />
    );
    expect(screen.queryByText("Provider Endpoint")).not.toBeInTheDocument();
  });

  it("encodes agent_key when pushing to /agents", () => {
    pushMock.mockClear();
    render(
      <AgentInfoModal
        agent={makeAgent({ agent_key: "weird/agent&name" })}
        hostAlias="wolf-i"
        onClose={() => {}}
      />
    );
    fireEvent.click(screen.getByText(/View Details/));
    expect(pushMock).toHaveBeenCalledWith(
      "/agents?key=weird%2Fagent%26name"
    );
  });

  it("returns null when agent is null", () => {
    const { container } = render(
      <AgentInfoModal agent={null} hostAlias="" onClose={() => {}} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("replaces all underscores in status text", () => {
    render(
      <AgentInfoModal
        agent={makeAgent({ status: "pending_onboard" })}
        hostAlias="wolf-i"
        onClose={() => {}}
      />
    );
    // status is rendered with all underscores swapped for spaces
    expect(screen.getByText("pending onboard")).toBeInTheDocument();
  });
});
