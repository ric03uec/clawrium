import type React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@xyflow/react", () => ({
  Handle: ({
    id,
    type,
    position,
    style,
  }: {
    id?: string;
    type: string;
    position: string;
    style?: React.CSSProperties;
  }) => (
    <div
      data-testid="rf-handle"
      data-handle-id={id ?? ""}
      data-handle-type={type}
      data-handle-position={position}
      data-handle-style={style ? JSON.stringify(style) : ""}
    />
  ),
  Position: { Top: "top", Bottom: "bottom", Left: "left", Right: "right" },
}));

import { AgentNode, type AgentNodeData } from "./agent-node";
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
    model: "claude-opus-4-7",
    version: "1.0.0",
    uptime: "1m",
    provider: "anthropic-prod",
    provider_type: "anthropic",
    provider_endpoint: null,
    provider_accelerator_vendor: null,
    ...overrides,
  };
  return {
    agent_name: merged.agent_key,
    ...merged,
  };
}

function renderNode(overrides: Partial<AgentNodeData> = {}) {
  const data: AgentNodeData = {
    agent: makeAgent(),
    hostname: "wolf-i",
    hostAlias: "wolf-i",
    hardware: null,
    hostColor: "#0D9488",
    ...overrides,
  };
  const props = { data } as unknown as Parameters<typeof AgentNode>[0];
  return render(<AgentNode {...props} />);
}

describe("AgentNode", () => {
  it("renders the agent name, type, model, and provider", () => {
    renderNode({ agent: makeAgent({ agent_key: "ada", model: "m1", provider: "p1" }) });
    expect(screen.getByText("ada")).toBeInTheDocument();
    expect(screen.getByText("zeroclaw")).toBeInTheDocument();
    expect(screen.getByText("m1")).toBeInTheDocument();
    expect(screen.getByText("p1")).toBeInTheDocument();
  });

  it("renders em-dash placeholders when model or provider are missing", () => {
    renderNode({ agent: makeAgent({ model: "", provider: "" }) });
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });

  it("renders the host alias in the bottom section", () => {
    renderNode({ hostAlias: "kevin-alias" });
    expect(screen.getByText("kevin-alias")).toBeInTheDocument();
  });

  it("applies the host color as the left border", () => {
    const { container } = renderNode({ hostColor: "#EC4899" });
    const root = container.firstElementChild as HTMLElement;
    // jsdom normalizes hex to rgb; just check the channel triplet.
    expect(root.style.borderLeft).toContain("rgb(236, 72, 153)");
  });

  it("fires onAgentClick with (agent, hostAlias) when the agent button is clicked", () => {
    const onAgentClick = vi.fn();
    const agent = makeAgent({ agent_key: "click-me" });
    renderNode({ agent, hostAlias: "host-x", onAgentClick });

    fireEvent.click(screen.getByText("click-me"));
    expect(onAgentClick).toHaveBeenCalledWith(agent, "host-x");
  });

  it("fires onHostClick with hostname when the host strip is clicked", () => {
    const onHostClick = vi.fn();
    renderNode({ hostname: "wolf-i", hostAlias: "wolf-i", onHostClick });

    fireEvent.click(screen.getByText("wolf-i"));
    expect(onHostClick).toHaveBeenCalledWith("wolf-i");
  });

  it("does not throw when click handlers are undefined", () => {
    renderNode({ onAgentClick: undefined, onHostClick: undefined });
    expect(() =>
      fireEvent.click(screen.getByText("agent-1"))
    ).not.toThrow();
  });

  it("declares an SSH target handle and provider source handle offset to avoid overlap", () => {
    renderNode();
    const handles = screen.getAllByTestId("rf-handle");
    const ssh = handles.find((h) => h.getAttribute("data-handle-id") === "ssh");
    const provider = handles.find(
      (h) => h.getAttribute("data-handle-id") === "provider"
    );
    expect(ssh?.getAttribute("data-handle-type")).toBe("target");
    expect(provider?.getAttribute("data-handle-type")).toBe("source");
    expect(ssh?.getAttribute("data-handle-style")).toContain("35%");
    expect(provider?.getAttribute("data-handle-style")).toContain("65%");
  });
});

describe("AgentNode HardwareTag", () => {
  it("renders nothing when hardware is null", () => {
    renderNode({ hardware: null });
    expect(screen.queryByText("GPU")).not.toBeInTheDocument();
    expect(screen.queryByText("NVIDIA")).not.toBeInTheDocument();
  });

  it("renders nothing when arch is unknown and GPU is absent", () => {
    renderNode({
      hardware: makeHardware({
        architecture: "unknown",
        gpu: { present: false, vendor: null, error: null },
      }),
    });
    expect(screen.queryByText("unknown")).not.toBeInTheDocument();
  });

  it("renders the architecture when present", () => {
    renderNode({
      hardware: makeHardware({ architecture: "x86_64" }),
    });
    expect(screen.getByText("x86_64")).toBeInTheDocument();
  });

  it("renders the NVIDIA badge for nvidia GPUs", () => {
    renderNode({
      hardware: makeHardware({
        gpu: { present: true, vendor: "nvidia", error: null },
      }),
    });
    expect(screen.getByText("NVIDIA")).toBeInTheDocument();
  });

  it("renders the AMD badge for amd GPUs", () => {
    renderNode({
      hardware: makeHardware({
        gpu: { present: true, vendor: "amd", error: null },
      }),
    });
    expect(screen.getByText("AMD")).toBeInTheDocument();
  });

  it("renders the Intel badge for intel GPUs", () => {
    renderNode({
      hardware: makeHardware({
        gpu: { present: true, vendor: "intel", error: null },
      }),
    });
    expect(screen.getByText("Intel")).toBeInTheDocument();
  });

  it("renders a generic GPU badge for null vendor when GPU is present", () => {
    renderNode({
      hardware: makeHardware({
        gpu: { present: true, vendor: null, error: null },
      }),
    });
    expect(screen.getByText("GPU")).toBeInTheDocument();
  });

  it("renders a generic GPU badge for unrecognized vendor strings", () => {
    renderNode({
      hardware: makeHardware({
        gpu: { present: true, vendor: "qualcomm", error: null },
      }),
    });
    expect(screen.getByText("GPU")).toBeInTheDocument();
  });
});
