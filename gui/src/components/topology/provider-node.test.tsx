import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("@xyflow/react", () => ({
  Handle: ({ id, type, position }: { id?: string; type: string; position: string }) => (
    <div data-testid="handle" data-handle-id={id} data-handle-type={type} data-handle-position={position} />
  ),
  Position: { Top: "top", Bottom: "bottom", Left: "left", Right: "right" },
}));

vi.mock("@/components/icons/aws", () => ({
  AwsIcon: ({ title }: { title?: string }) => <svg data-testid="icon-aws" aria-label={title} />,
}));
vi.mock("@/components/icons/anthropic", () => ({
  AnthropicIcon: ({ title }: { title?: string }) => <svg data-testid="icon-anthropic" aria-label={title} />,
}));
vi.mock("@/components/icons/openai", () => ({
  OpenAiIcon: ({ title }: { title?: string }) => <svg data-testid="icon-openai" aria-label={title} />,
}));
vi.mock("@/components/icons/google-cloud", () => ({
  GoogleCloudIcon: ({ title }: { title?: string }) => <svg data-testid="icon-gcloud" aria-label={title} />,
}));
vi.mock("@/components/icons/openrouter", () => ({
  OpenRouterIcon: ({ title }: { title?: string }) => <svg data-testid="icon-openrouter" aria-label={title} />,
}));
vi.mock("@/components/icons/ollama", () => ({
  OllamaIcon: ({ title }: { title?: string }) => <svg data-testid="icon-ollama" aria-label={title} />,
}));
vi.mock("@/components/icons/zhipu", () => ({
  ZhipuIcon: ({ title }: { title?: string }) => <svg data-testid="icon-zhipu" aria-label={title} />,
}));
vi.mock("@/components/icons/nvidia", () => ({
  NvidiaIcon: ({ title }: { title?: string }) => <svg data-testid="icon-nvidia" aria-label={title} />,
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
  it("renders the Ollama icon and label for ollama type", () => {
    renderNode({ name: "local-inx", type: "ollama" });
    expect(screen.getByTestId("icon-ollama")).toBeInTheDocument();
    expect(screen.getByText("Ollama")).toBeInTheDocument();
    expect(screen.getByText("local-inx")).toBeInTheDocument();
  });

  it("renders the AWS icon and 'AWS Bedrock' label for bedrock type", () => {
    renderNode({ name: "my-bedrock", type: "bedrock" });
    expect(screen.getByTestId("icon-aws")).toBeInTheDocument();
    expect(screen.getByText("AWS Bedrock")).toBeInTheDocument();
  });

  it("renders the Anthropic icon for anthropic type", () => {
    renderNode({ name: "claude-api", type: "anthropic" });
    expect(screen.getByTestId("icon-anthropic")).toBeInTheDocument();
    expect(screen.getByText("Anthropic")).toBeInTheDocument();
  });

  it("renders the OpenAI icon for openai type", () => {
    renderNode({ name: "gpt-api", type: "openai" });
    expect(screen.getByTestId("icon-openai")).toBeInTheDocument();
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
  });

  it("renders Google Cloud icon for vertex type", () => {
    renderNode({ name: "vertex-ai", type: "vertex" });
    expect(screen.getByTestId("icon-gcloud")).toBeInTheDocument();
    expect(screen.getByText("Google Vertex")).toBeInTheDocument();
  });

  it("renders OpenRouter icon for openrouter type", () => {
    renderNode({ name: "router-1", type: "openrouter" });
    expect(screen.getByTestId("icon-openrouter")).toBeInTheDocument();
    expect(screen.getByText("OpenRouter")).toBeInTheDocument();
  });

  it("renders Zhipu icon for zai type", () => {
    renderNode({ name: "zhipu-1", type: "zai" });
    expect(screen.getByTestId("icon-zhipu")).toBeInTheDocument();
    expect(screen.getByText("Zhipu AI")).toBeInTheDocument();
  });

  it("uses NVIDIA branding when ollama + nvidia GPU vendor", () => {
    renderNode({
      name: "local-ollama",
      type: "ollama",
      hostGpuVendor: "nvidia",
    });
    expect(screen.getByTestId("icon-nvidia")).toBeInTheDocument();
    expect(screen.getByText(/NVIDIA/)).toBeInTheDocument();
  });

  it("falls back to 'Provider' label when type is null", () => {
    renderNode({ name: "Unconfigured", type: null, unconfigured: true });
    expect(screen.getByText("Provider")).toBeInTheDocument();
  });

  it("shows the endpoint sub-line when endpoint is truthy", () => {
    renderNode({ endpoint: "http://10.0.0.5:11434" });
    expect(screen.getByText("http://10.0.0.5:11434")).toBeInTheDocument();
  });

  it("hides the endpoint sub-line when endpoint is null", () => {
    const { container } = renderNode({ endpoint: null });
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

  it("renders 0 agents when configured provider has no agents", () => {
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

  it("applies inline dashed border-left when unconfigured", () => {
    const { container } = renderNode({
      unconfigured: true,
      type: null,
      name: "Unconfigured",
    });
    const card = container.firstChild as HTMLElement;
    expect(card.style.borderLeft).toContain("dashed");
  });

  it("applies solid left border with accent color when configured", () => {
    const { container } = renderNode({ unconfigured: false, type: "ollama" });
    const card = container.firstChild as HTMLElement;
    expect(card.style.borderLeft).toContain("solid");
    // jsdom serializes hex #808080 to rgb(128, 128, 128)
    expect(card.style.borderLeft).toMatch(/rgb\(128,\s*128,\s*128\)|#808080/);
  });
});
