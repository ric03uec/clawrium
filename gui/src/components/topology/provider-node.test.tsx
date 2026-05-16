import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("@xyflow/react", () => ({
  Handle: ({ id, type, position }: { id?: string; type: string; position: string }) => (
    <div data-testid="handle" data-handle-id={id} data-handle-type={type} data-handle-position={position} />
  ),
  Position: { Top: "top", Bottom: "bottom", Left: "left", Right: "right" },
}));

import { ProviderNode } from "./provider-node";
import { type ProviderNodeData } from "./topology-graph";

function renderNode(data: Partial<ProviderNodeData>) {
  const full: ProviderNodeData = {
    providerKey: "k",
    name: "p",
    type: "ollama",
    endpoint: null,
    agentCount: 1,
    unconfigured: false,
    ...data,
  };
  const props = { data: full } as unknown as Parameters<typeof ProviderNode>[0];
  return render(<ProviderNode {...props} />);
}

describe("ProviderNode", () => {
  it("renders the typed label and glyph for a known type", () => {
    renderNode({ name: "local-inx", type: "ollama" });
    expect(screen.getByText("Ollama")).toBeInTheDocument();
    expect(screen.getByText("L")).toBeInTheDocument();
    expect(screen.getByText("local-inx")).toBeInTheDocument();
  });

  it("falls back to 'Provider' and '?' when type is null", () => {
    renderNode({ name: "Unconfigured", type: null, unconfigured: true });
    expect(screen.getByText("Provider")).toBeInTheDocument();
    expect(screen.getByText("?")).toBeInTheDocument();
  });

  it("falls back to capitalized first char for unknown type", () => {
    renderNode({ name: "weird", type: "vertex" });
    expect(screen.getByText("V")).toBeInTheDocument();
    // Unknown type label falls through to the raw string.
    expect(screen.getByText("vertex")).toBeInTheDocument();
  });

  it("shows the endpoint sub-line when endpoint is truthy", () => {
    renderNode({ endpoint: "http://10.0.0.5:11434" });
    expect(screen.getByText("http://10.0.0.5:11434")).toBeInTheDocument();
  });

  it("hides the endpoint sub-line when endpoint is null", () => {
    const { container } = renderNode({ endpoint: null });
    // No element should contain a URL-like substring
    expect(container.textContent).not.toMatch(/http:\/\//);
  });

  it("shows agent count for configured providers", () => {
    renderNode({ agentCount: 3, unconfigured: false });
    expect(screen.getByText("3 agents")).toBeInTheDocument();
  });

  it("uses singular noun for one agent", () => {
    renderNode({ agentCount: 1, unconfigured: false });
    expect(screen.getByText("1 agent")).toBeInTheDocument();
  });

  it("renders 0 agents for a configured provider with no agents", () => {
    renderNode({ agentCount: 0, unconfigured: false });
    expect(screen.getByText("0 agents")).toBeInTheDocument();
  });

  it("hides agent count when unconfigured", () => {
    const { container } = renderNode({
      agentCount: 2,
      unconfigured: true,
      type: null,
      name: "Unconfigured",
    });
    expect(container.textContent).not.toMatch(/agents?/);
  });

  it("applies a dashed border when unconfigured", () => {
    const { container } = renderNode({
      unconfigured: true,
      type: null,
      name: "Unconfigured",
    });
    const card = container.firstChild as HTMLElement;
    expect(card.className).toMatch(/border-dashed/);
  });

  it("applies the primary border when configured", () => {
    const { container } = renderNode({ unconfigured: false });
    const card = container.firstChild as HTMLElement;
    expect(card.className).not.toMatch(/border-dashed/);
    expect(card.className).toMatch(/border-primary/);
  });
});
