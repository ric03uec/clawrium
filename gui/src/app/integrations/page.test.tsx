import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Integration, IntegrationTypesMap } from "@/lib/types";

const integrationsState: {
  data: Integration[] | undefined;
  isLoading: boolean;
} = { data: undefined, isLoading: false };
const integrationTypesState: {
  data: IntegrationTypesMap | undefined;
  isLoading: boolean;
} = { data: undefined, isLoading: false };

vi.mock("@/hooks", () => ({
  useIntegrations: () => integrationsState,
  useIntegrationTypes: () => integrationTypesState,
  useIntegration: () => ({ data: undefined, isLoading: false }),
  useCreateIntegration: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteIntegration: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateIntegrationCredentials: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/components/ui/modal", () => ({
  Modal: ({
    open,
    title,
    children,
  }: {
    open: boolean;
    title: string;
    children: React.ReactNode;
  }) =>
    open ? (
      <div data-testid="modal">
        <p>{title}</p>
        {children}
      </div>
    ) : null,
}));

import IntegrationsPage from "./page";

function makeIntegration(overrides: Partial<Integration> = {}): Integration {
  return {
    name: "mygh",
    type: "github",
    credential_keys: ["GITHUB_TOKEN"],
    configured_credential_keys: ["GITHUB_TOKEN"],
    agent_count: 0,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

describe("IntegrationsPage", () => {
  it("renders Add Integration in the list-section row, not the page header (#786)", () => {
    integrationsState.data = [makeIntegration()];
    integrationTypesState.data = {};

    render(<IntegrationsPage />);

    const heading = screen.getByText(/Configured Integrations \(1\)/);
    const sectionRow = heading.parentElement!;
    expect(
      within(sectionRow).getByRole("button", { name: /Add Integration/ }),
    ).toBeInTheDocument();

    const pageHeader = screen.getByTestId("page-header");
    expect(
      within(pageHeader).queryByRole("button", { name: /Add Integration/ }),
    ).toBeNull();
  });

  it("shows the empty-state CTA when no integrations exist (#786 acceptance)", () => {
    integrationsState.data = [];
    integrationTypesState.data = {};

    render(<IntegrationsPage />);

    expect(
      screen.getByText("No integrations configured yet."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Add your first integration/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Configured Integrations/),
    ).toBeNull();

    // W5 invariant must hold on the empty branch too: the Add affordance
    // is the empty-state CTA only — there must not be a duplicate in the
    // page header.
    const pageHeader = screen.getByTestId("page-header");
    expect(
      within(pageHeader).queryByRole("button", { name: /Add Integration/ }),
    ).toBeNull();
  });
});
