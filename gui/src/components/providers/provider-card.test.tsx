import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/icons/aws", () => ({
  AwsIcon: ({ title }: { title?: string }) => (
    <svg data-testid="icon-aws" aria-label={title} />
  ),
}));
vi.mock("@/components/icons/anthropic", () => ({
  AnthropicIcon: ({ title }: { title?: string }) => (
    <svg data-testid="icon-anthropic" aria-label={title} />
  ),
}));
vi.mock("@/components/icons/openai", () => ({
  OpenAiIcon: ({ title }: { title?: string }) => (
    <svg data-testid="icon-openai" aria-label={title} />
  ),
}));
vi.mock("@/components/icons/google-cloud", () => ({
  GoogleCloudIcon: ({ title }: { title?: string }) => (
    <svg data-testid="icon-gcloud" aria-label={title} />
  ),
}));
vi.mock("@/components/icons/openrouter", () => ({
  OpenRouterIcon: ({ title }: { title?: string }) => (
    <svg data-testid="icon-openrouter" aria-label={title} />
  ),
}));
vi.mock("@/components/icons/ollama", () => ({
  OllamaIcon: ({ title }: { title?: string }) => (
    <svg data-testid="icon-ollama" aria-label={title} />
  ),
}));
vi.mock("@/components/icons/zhipu", () => ({
  ZhipuIcon: ({ title }: { title?: string }) => (
    <svg data-testid="icon-zhipu" aria-label={title} />
  ),
}));
vi.mock("@/components/icons/nvidia", () => ({
  NvidiaIcon: ({ title }: { title?: string }) => (
    <svg data-testid="icon-nvidia" aria-label={title} />
  ),
}));
vi.mock("@/components/icons/amd", () => ({
  AmdIcon: ({ title }: { title?: string }) => (
    <svg data-testid="icon-amd" aria-label={title} />
  ),
}));

import { ProviderCard } from "./provider-card";
import type { Provider } from "@/lib/types";

function makeProvider(overrides: Partial<Provider> = {}): Provider {
  return {
    name: "local-llm",
    type: "ollama",
    endpoint: "http://10.0.0.5:11434",
    default_model: "llama3.1:8b",
    available_models: null,
    has_api_key: false,
    accelerator_vendor: "nvidia",
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

describe("ProviderCard accelerator tile", () => {
  it("shows Ollama logo + NVIDIA badge when accelerator_vendor is nvidia", () => {
    render(
      <ProviderCard
        provider={makeProvider({ accelerator_vendor: "nvidia" })}
        usedBy={[]}
        onEdit={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByTestId("icon-ollama")).toBeInTheDocument();
    expect(screen.getByTestId("icon-nvidia")).toBeInTheDocument();
    expect(screen.getByText("Ollama")).toBeInTheDocument();
    expect(screen.getByText("NVIDIA")).toBeInTheDocument();
  });

  it("shows Ollama logo + AMD badge when accelerator_vendor is amd", () => {
    render(
      <ProviderCard
        provider={makeProvider({ accelerator_vendor: "amd" })}
        usedBy={[]}
        onEdit={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByTestId("icon-ollama")).toBeInTheDocument();
    expect(screen.getByTestId("icon-amd")).toBeInTheDocument();
    expect(screen.getByText("AMD")).toBeInTheDocument();
    expect(screen.queryByTestId("icon-nvidia")).not.toBeInTheDocument();
  });

  it("does not render an accelerator badge for cloud providers", () => {
    render(
      <ProviderCard
        provider={makeProvider({
          name: "claude-prod",
          type: "anthropic",
          endpoint: null,
          default_model: "claude-sonnet-4-5",
          accelerator_vendor: null,
        })}
        usedBy={[]}
        onEdit={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByTestId("icon-anthropic")).toBeInTheDocument();
    expect(screen.queryByTestId("icon-nvidia")).not.toBeInTheDocument();
    expect(screen.queryByTestId("icon-amd")).not.toBeInTheDocument();
    expect(screen.queryByText("NVIDIA")).not.toBeInTheDocument();
    expect(screen.queryByText("AMD")).not.toBeInTheDocument();
  });
});
