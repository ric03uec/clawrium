import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CatalogModel, ProviderTypesMap } from "@/lib/types";

const useModelCatalog = vi.fn();

const providerTypes: ProviderTypesMap = {
  anthropic: {
    endpoint: null,
    models: [
      {
        id: "claude-sonnet",
        name: "Claude Sonnet",
        lab: "Anthropic",
        context_window: 200000,
        tags: ["chat"],
      },
    ],
    requires_api_key: true,
    requires_endpoint: false,
  },
  ollama: {
    endpoint: null,
    models: [],
    requires_api_key: false,
    requires_endpoint: true,
  },
  openai: {
    endpoint: null,
    models: [
      {
        id: "gpt-4o",
        name: "GPT-4o",
        lab: "OpenAI",
        context_window: 128000,
        tags: ["multimodal"],
      },
    ],
    requires_api_key: true,
    requires_endpoint: false,
  },
};

const allModels: CatalogModel[] = [
  {
    id: "alpha-id",
    name: "Friendly Alpha",
    lab: "OpenAI",
    context_window: 128000,
    tags: ["chat", "tools"],
    provider_type: "openai",
  },
  {
    id: "claude-sonnet",
    name: "Claude Sonnet",
    lab: "Anthropic",
    context_window: 1000000,
    tags: ["chat"],
    provider_type: "anthropic",
  },
];

vi.mock("@/hooks/use-providers", () => ({
  useProviderTypes: () => ({ data: providerTypes, isLoading: false }),
  useModelCatalog: (...args: unknown[]) => useModelCatalog(...args),
}));

import { ModelCatalog } from "./model-catalog";

beforeEach(() => {
  useModelCatalog.mockImplementation((provider?: string) => ({
    data:
      provider === "anthropic"
        ? allModels.filter((model) => model.provider_type === "anthropic")
        : allModels,
    isLoading: false,
  }));
});

describe("ModelCatalog", () => {
  it("filters by model id or name and resets search when provider changes", async () => {
    const user = userEvent.setup();
    render(<ModelCatalog />);

    expect(useModelCatalog).toHaveBeenCalledWith(undefined, undefined, 500);
    expect(screen.getByRole("columnheader", { name: "Provider" })).toBeInTheDocument();
    expect(screen.getByText("128K")).toBeInTheDocument();
    expect(screen.getByText("1.0M")).toBeInTheDocument();
    expect(screen.getByText("tools")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /openai alpha-id/ })).toHaveAttribute(
      "data-row-id",
      "openai:alpha-id",
    );

    const search = screen.getByRole("searchbox", { name: "Search table" });
    await user.type(search, "Friendly Alpha");
    expect(screen.getByText("alpha-id")).toBeInTheDocument();
    expect(screen.queryByText("claude-sonnet")).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "anthropic");
    expect(screen.getByText("No models found")).toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "Model provider" }), "anthropic");

    expect(useModelCatalog).toHaveBeenLastCalledWith("anthropic", undefined, undefined);
    expect(screen.getByRole("searchbox", { name: "Search table" })).toHaveValue("");
    expect(screen.getByText("claude-sonnet")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Provider" })).not.toBeInTheDocument();
  });

  it("keeps identical model IDs collision-free across providers", () => {
    useModelCatalog.mockReturnValue({
      data: [
        { ...allModels[0], id: "shared-model", provider_type: "openai" },
        { ...allModels[1], id: "shared-model", provider_type: "anthropic" },
      ],
      isLoading: false,
    });

    const { container } = render(<ModelCatalog />);
    expect(container.querySelector('[data-row-id="openai:shared-model"]')).toBeInTheDocument();
    expect(container.querySelector('[data-row-id="anthropic:shared-model"]')).toBeInTheDocument();
  });

  it("shows the host-specific Ollama message and provider counts", async () => {
    const user = userEvent.setup();
    render(<ModelCatalog />);

    const selector = screen.getByRole("combobox", { name: "Model provider" });
    expect(
      within(selector).getByRole("option", { name: "All providers (2 models)" }),
    ).toBeInTheDocument();
    expect(
      within(selector).getByRole("option", { name: "ollama (per-host)" }),
    ).toBeInTheDocument();

    await user.selectOptions(selector, "ollama");

    expect(
      screen.getByText(/Models are discovered per-host from the Ollama daemon/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });

  it("paginates model results in 50-row pages and reports totals", async () => {
    const user = userEvent.setup();
    const manyModels = Array.from({ length: 51 }, (_, index): CatalogModel => ({
      id: `model-${String(index + 1).padStart(2, "0")}`,
      name: `Model ${index + 1}`,
      lab: "Test",
      context_window: 8192,
      tags: [],
      provider_type: "openai",
    }));
    useModelCatalog.mockReturnValue({ data: manyModels, isLoading: false });

    render(<ModelCatalog />);

    expect(screen.getByText("51 models")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–50 of 51")).toBeInTheDocument();
    expect(screen.getByText("model-01")).toBeInTheDocument();
    expect(screen.queryByText("model-51")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next page" }));

    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
    expect(screen.getByText("Showing 51–51 of 51")).toBeInTheDocument();
    expect(screen.getByText("model-51")).toBeInTheDocument();
    expect(screen.queryByText("model-01")).not.toBeInTheDocument();
  });
});
