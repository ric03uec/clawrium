import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@xyflow/react", () => ({
  Handle: ({
    id,
    type,
    position,
  }: {
    id?: string;
    type: string;
    position: string;
  }) => (
    <div
      data-testid="rf-handle"
      data-handle-id={id ?? ""}
      data-handle-type={type}
      data-handle-position={position}
    />
  ),
  Position: { Top: "top", Bottom: "bottom", Left: "left", Right: "right" },
}));

import { HostNode } from "./host-node";
import { type TopologyAgent } from "@/lib/types";

function makeAgent(overrides: Partial<TopologyAgent> = {}): TopologyAgent {
  const merged = {
    agent_key: "agent-1",
    agent_type: "zeroclaw",
    status: "running" as const,
    model: "m",
    version: "1.0.0",
    uptime: "1m",
    provider: "p",
    provider_type: "ollama",
    provider_endpoint: null,
    ...overrides,
  };
  return {
    agent_name: merged.agent_key,
    ...merged,
  };
}

function renderHost(
  agents: TopologyAgent[],
  callbacks: {
    onAgentClick?: (agent: TopologyAgent) => void;
    onHostClick?: (hostname: string) => void;
  } = {}
) {
  const data = {
    hostname: "wolf-i",
    alias: "wolf-i",
    user: "alice",
    agentCount: agents.length,
    agents,
    ...callbacks,
  };
  const props = { data } as unknown as Parameters<typeof HostNode>[0];
  return render(<HostNode {...props} />);
}

describe("HostNode", () => {
  it("renders one source Handle per agent with id=agent_key", () => {
    const agents = [
      makeAgent({ agent_key: "espresso" }),
      makeAgent({ agent_key: "maurice" }),
      makeAgent({ agent_key: "zc-test" }),
    ];
    renderHost(agents);

    const handles = screen.getAllByTestId("rf-handle");
    const sourceHandles = handles.filter(
      (h) => h.getAttribute("data-handle-type") === "source"
    );
    expect(sourceHandles).toHaveLength(3);
    expect(
      sourceHandles.map((h) => h.getAttribute("data-handle-id")).sort()
    ).toEqual(["espresso", "maurice", "zc-test"]);
  });

  it("renders exactly one top target handle for the SSH edge", () => {
    renderHost([makeAgent({ agent_key: "espresso" })]);
    const handles = screen.getAllByTestId("rf-handle");
    const targetHandles = handles.filter(
      (h) => h.getAttribute("data-handle-type") === "target"
    );
    expect(targetHandles).toHaveLength(1);
    expect(targetHandles[0].getAttribute("data-handle-position")).toBe("top");
  });

  it("renders 'No agents' placeholder for empty hosts", () => {
    renderHost([]);
    expect(screen.getByText("No agents")).toBeInTheDocument();
    expect(
      screen
        .getAllByTestId("rf-handle")
        .filter((h) => h.getAttribute("data-handle-type") === "source")
    ).toHaveLength(0);
  });

  it("invokes onAgentClick with the clicked agent", () => {
    const onAgentClick = vi.fn();
    const agent = makeAgent({ agent_key: "espresso" });
    renderHost([agent], { onAgentClick });

    fireEvent.click(screen.getByText("espresso"));
    expect(onAgentClick).toHaveBeenCalledWith(agent);
  });

  it("invokes onHostClick with the hostname when the header is clicked", () => {
    const onHostClick = vi.fn();
    renderHost([], { onHostClick });

    fireEvent.click(screen.getByText("wolf-i"));
    expect(onHostClick).toHaveBeenCalledWith("wolf-i");
  });

  it("does not throw when callbacks are undefined", () => {
    const agent = makeAgent({ agent_key: "espresso" });
    renderHost([agent]);
    // Clicking the agent and the host should be no-ops, not throws.
    fireEvent.click(screen.getByText("espresso"));
    fireEvent.click(screen.getByText("wolf-i"));
  });
});
