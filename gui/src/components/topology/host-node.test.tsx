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
import { type HostHardware, type TopologyAgent } from "@/lib/types";

function makeHardware(overrides: Partial<HostHardware> = {}): HostHardware {
  return {
    architecture: null,
    cores: null,
    memtotal_mb: null,
    gpu: { present: false, vendor: null, error: null },
    product_name: null,
    system_vendor: null,
    ...overrides,
  };
}

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
    hardware?: HostHardware | null;
  } = {}
) {
  const { hardware, ...cb } = callbacks;
  const data = {
    hostname: "wolf-i",
    alias: "wolf-i",
    user: "alice",
    agentCount: agents.length,
    agents,
    hardware: hardware ?? null,
    ...cb,
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

  it("renders agents as columns (each with its own bottom source handle)", () => {
    const agents = [
      makeAgent({ agent_key: "espresso", model: "claude-1" }),
      makeAgent({ agent_key: "maurice", model: "gpt-4" }),
    ];
    renderHost(agents);
    const sources = screen
      .getAllByTestId("rf-handle")
      .filter((h) => h.getAttribute("data-handle-type") === "source");
    expect(sources).toHaveLength(2);
    sources.forEach((h) =>
      expect(h.getAttribute("data-handle-position")).toBe("bottom"),
    );
  });

  it("renders architecture badge when known", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({ architecture: "aarch64" }),
    });
    expect(screen.getByText("aarch64")).toBeInTheDocument();
  });

  it("omits architecture badge when architecture is 'unknown'", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({ architecture: "unknown" }),
    });
    expect(screen.queryByText("unknown")).not.toBeInTheDocument();
  });

  it("renders NVIDIA GPU badge with vendor text when GPU detected", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({
        architecture: "x86_64",
        gpu: { present: true, vendor: "nvidia", error: null },
      }),
    });
    expect(screen.getByText("NVIDIA")).toBeInTheDocument();
  });

  it("renders AMD GPU badge with vendor text when GPU detected", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({
        gpu: { present: true, vendor: "amd", error: null },
      }),
    });
    expect(screen.getByText("AMD")).toBeInTheDocument();
  });

  it("renders Intel GPU badge with vendor text when GPU detected", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({
        gpu: { present: true, vendor: "intel", error: null },
      }),
    });
    expect(screen.getByText("Intel")).toBeInTheDocument();
  });

  it("renders generic GPU badge when vendor is unknown", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({
        gpu: { present: true, vendor: "unknown", error: null },
      }),
    });
    expect(screen.getByText("GPU")).toBeInTheDocument();
  });

  it("does not render a GPU badge when GPU is absent", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({
        gpu: { present: false, vendor: null, error: null },
      }),
    });
    expect(screen.queryByText("NVIDIA")).not.toBeInTheDocument();
    expect(screen.queryByText("AMD")).not.toBeInTheDocument();
    expect(screen.queryByText("Intel")).not.toBeInTheDocument();
    expect(screen.queryByText("GPU")).not.toBeInTheDocument();
  });

  it("renders product_name as a sub-line for NVIDIA system vendor", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({
        system_vendor: "nvidia",
        product_name: "DGX Spark",
      }),
    });
    expect(screen.getByText("DGX Spark")).toBeInTheDocument();
  });

  it("renders product_name sub-line even when GPU was not detected on NVIDIA system", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({
        system_vendor: "nvidia",
        product_name: "DGX Spark",
        gpu: { present: false, vendor: null, error: null },
      }),
    });
    expect(screen.getByText("DGX Spark")).toBeInTheDocument();
  });

  it("renders product_name without a vendor logo when system_vendor is not nvidia", () => {
    renderHost([makeAgent()], {
      hardware: makeHardware({
        system_vendor: "dell inc.",
        product_name: "PowerEdge R750",
      }),
    });
    expect(screen.getByText("PowerEdge R750")).toBeInTheDocument();
    expect(screen.queryByText("NVIDIA")).not.toBeInTheDocument();
  });

  it("renders nothing hardware-related when host has no hardware block", () => {
    renderHost([makeAgent()]);
    expect(screen.queryByText("aarch64")).not.toBeInTheDocument();
    expect(screen.queryByText("NVIDIA")).not.toBeInTheDocument();
    expect(screen.queryByText("AMD")).not.toBeInTheDocument();
    expect(screen.queryByText("Intel")).not.toBeInTheDocument();
    expect(screen.queryByText("GPU")).not.toBeInTheDocument();
  });
});
