import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  Integration,
  IntegrationDetail,
  IntegrationTypesMap,
} from "@/lib/types";

const integrationsState: {
  data: Integration[] | undefined;
  isLoading: boolean;
} = { data: undefined, isLoading: false };
const integrationTypesState: {
  data: IntegrationTypesMap | undefined;
  isLoading: boolean;
} = { data: undefined, isLoading: false };
const integrationDetailState: {
  data: IntegrationDetail | undefined;
  isLoading: boolean;
} = { data: undefined, isLoading: false };
const mutationState = {
  createPending: false,
  deletePending: false,
  updatePending: false,
};
const createMutate = vi.fn();
const deleteMutate = vi.fn();
const updateMutate = vi.fn();

vi.mock("@/hooks", () => ({
  useIntegrations: () => integrationsState,
  useIntegrationTypes: () => integrationTypesState,
  useIntegration: () => integrationDetailState,
  useCreateIntegration: () => ({
    mutate: createMutate,
    isPending: mutationState.createPending,
  }),
  useDeleteIntegration: () => ({
    mutate: deleteMutate,
    isPending: mutationState.deletePending,
  }),
  useUpdateIntegrationCredentials: () => ({
    mutate: updateMutate,
    isPending: mutationState.updatePending,
  }),
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
      <div role="dialog" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    ) : null,
}));

import IntegrationsPage from "./page";

const TYPES: IntegrationTypesMap = {
  github: {
    description: "GitHub for code hosting",
    credentials: [
      {
        key: "GITHUB_TOKEN",
        description: "Personal access token",
        required: true,
      },
    ],
  },
  gitlab: {
    description: "GitLab for code hosting",
    credentials: [
      {
        key: "GITLAB_TOKEN",
        description: "Personal access token",
        required: true,
      },
    ],
  },
};

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

beforeEach(() => {
  integrationsState.data = undefined;
  integrationsState.isLoading = false;
  integrationTypesState.data = TYPES;
  integrationTypesState.isLoading = false;
  integrationDetailState.data = undefined;
  integrationDetailState.isLoading = false;
  mutationState.createPending = false;
  mutationState.deletePending = false;
  mutationState.updatePending = false;
  createMutate.mockReset();
  deleteMutate.mockReset();
  updateMutate.mockReset();
});

describe("IntegrationsPage", () => {
  it("renders the loading state through the design-system table", () => {
    integrationsState.isLoading = true;

    render(<IntegrationsPage />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.getByRole("cell", { name: "Loading integrations..." }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Configured Integrations")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("shows the empty-state CTA and preserves the add flow and error", async () => {
    const user = userEvent.setup();
    integrationsState.data = [];

    render(<IntegrationsPage />);

    expect(
      screen.getByText("No integrations configured yet."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Add your first integration/ }),
    );
    const dialog = screen.getByRole("dialog", { name: "Add Integration" });
    await user.type(
      within(dialog).getByRole("textbox", { name: "Integration name" }),
      "new-gh",
    );
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Type" }),
      "github",
    );
    await user.type(within(dialog).getByLabelText("GITHUB_TOKEN*"), "secret");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(createMutate).toHaveBeenCalledWith(
      {
        name: "new-gh",
        type: "github",
        credentials: { GITHUB_TOKEN: "secret" },
      },
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );

    act(() => {
      createMutate.mock.calls[0][1].onError(new Error("Could not add"));
    });
    expect(screen.getByText("Could not add")).toBeInTheDocument();
  });

  it("renders searchable identity, status, agent counts, and list actions", async () => {
    const user = userEvent.setup();
    integrationsState.data = [
      makeIntegration({ agent_count: 1 }),
      makeIntegration({
        name: "team-gitlab",
        type: "gitlab",
        credential_keys: ["GITLAB_TOKEN"],
        configured_credential_keys: [],
        agent_count: 0,
      }),
    ];

    render(<IntegrationsPage />);

    expect(screen.getByRole("columnheader", { name: /Integration/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Type/ })).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /Credential status/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Agents using/ })).toBeInTheDocument();
    expect(screen.getByText("Credentials configured")).toBeInTheDocument();
    expect(screen.getByText("Credentials incomplete")).toBeInTheDocument();
    expect(screen.getByText("1/1 set")).toBeInTheDocument();
    expect(screen.getByText("0/1 set")).toBeInTheDocument();
    expect(screen.getByText("1 agent")).toBeInTheDocument();
    expect(screen.getByText("No agents")).toBeInTheDocument();
    expect(screen.getByText("2 integrations")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Add Integration/ }),
    ).toBeInTheDocument();

    await user.type(
      screen.getByRole("searchbox", { name: "Search Configured Integrations" }),
      "team-gitlab",
    );
    expect(screen.queryByText("mygh")).not.toBeInTheDocument();
    expect(screen.getByText("team-gitlab")).toBeInTheDocument();
    expect(screen.getByText("1 integration")).toBeInTheDocument();
  });

  it("opens masked credential details from the named identity button and keeps the update payload unchanged", async () => {
    const user = userEvent.setup();
    integrationsState.data = [makeIntegration()];

    render(<IntegrationsPage />);

    const row = screen.getByRole("row", { name: /mygh/ });
    expect(row).toHaveAttribute("data-row-id", "mygh");
    expect(row).not.toHaveAttribute("tabindex");
    await user.click(within(row).getByRole("button", { name: "Edit credentials for mygh" }));
    const dialog = screen.getByRole("dialog", {
      name: "Edit credentials — mygh",
    });
    const credential = within(dialog).getByLabelText("GITHUB_TOKEN (set)");
    expect(credential).toHaveAttribute("type", "password");
    expect(credential).toHaveValue("");

    await user.type(credential, "replacement-token");
    await user.click(
      within(dialog).getByRole("button", { name: "Update credentials" }),
    );

    expect(updateMutate).toHaveBeenCalledWith(
      {
        name: "mygh",
        data: { credentials: { GITHUB_TOKEN: "replacement-token" } },
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("opens the edit dialog from the nested edit action", async () => {
    const user = userEvent.setup();
    integrationsState.data = [makeIntegration()];

    render(<IntegrationsPage />);

    await user.click(
      screen.getByRole("button", { name: "Edit credentials" }),
    );
    expect(
      screen.getByRole("dialog", { name: "Edit credentials — mygh" }),
    ).toBeInTheDocument();
  });

  it("keeps remove separate from edit actions and reports blocking agents and delete errors", async () => {
    const user = userEvent.setup();
    const integration = makeIntegration({ agent_count: 2 });
    integrationsState.data = [integration];
    integrationDetailState.data = {
      ...integration,
      agents_using: [
        { hostname: "host-a", agent_key: "alpha" },
        { hostname: "host-b", agent_key: "beta" },
      ],
    };

    render(<IntegrationsPage />);

    await user.click(screen.getByRole("button", { name: "Remove" }));
    const dialog = screen.getByRole("dialog", { name: "Remove Integration" });
    expect(
      screen.queryByRole("dialog", { name: "Edit credentials — mygh" }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getByText("In use by 2 agents:")).toBeInTheDocument();
    expect(within(dialog).getByText(/host-a/)).toBeInTheDocument();
    expect(within(dialog).getByText(/alpha/)).toBeInTheDocument();
    expect(
      within(dialog).getByText("Remove the assignment from those agents first."),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(deleteMutate).toHaveBeenCalledWith(
      "mygh",
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );

    act(() => {
      deleteMutate.mock.calls[0][1].onError(new Error("Integration is in use"));
    });
    expect(
      within(dialog).getByText("Integration is in use"),
    ).toBeInTheDocument();
  });
});
