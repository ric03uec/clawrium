import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/use-providers", () => ({
  useProviders: () => ({ data: [{ name: "one" }, { name: "two" }], isLoading: false }),
  useProviderTypes: () => ({ data: {} }),
  useCreateProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteProvider: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/use-fleet", () => ({
  useFleet: () => ({ data: { agents: [] } }),
}));

vi.mock("@/components/providers", () => ({
  ProvidersTable: () => <div>Configured providers content</div>,
  AddProviderModal: () => null,
  EditProviderModal: () => null,
  ModelCatalog: () => <div>Registry content</div>,
}));

vi.mock("@/components/ui/modal", () => ({ Modal: () => null }));

import ProvidersPage from "./page";

describe("ProvidersPage tabs", () => {
  it("preserves configured default, count, and registry callback", () => {
    render(<ProvidersPage />);

    const tablist = screen.getByRole("tablist", { name: "Providers tabs" });
    expect(tablist).toHaveAttribute("data-i7n-name", "providers.page.tabs");
    const configuredTab = screen.getByRole("tab", { name: "Configured (2)" });
    expect(configuredTab).toHaveAttribute("aria-selected", "true");
    expect(configuredTab).toHaveAttribute("aria-controls", "providers-page-tabs-panel-configured");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", configuredTab.id);
    expect(screen.getByText("Configured providers content")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Registry" }));
    const registryTab = screen.getByRole("tab", { name: "Registry" });
    expect(registryTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", registryTab.id);
    expect(screen.getByText("Registry content")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+ Add model provider" })).not.toBeInTheDocument();
  });
});
