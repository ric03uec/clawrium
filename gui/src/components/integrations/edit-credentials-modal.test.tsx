import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui/modal", () => ({
  Modal: ({
    open,
    children,
    title,
  }: {
    open: boolean;
    children: React.ReactNode;
    title: string;
  }) =>
    open ? (
      <div role="dialog" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    ) : null,
}));

import { EditCredentialsModal } from "./edit-credentials-modal";
import type { Integration, IntegrationTypesMap } from "@/lib/types";

const TYPES: IntegrationTypesMap = {
  github: {
    description: "GitHub",
    credentials: [
      { key: "GITHUB_TOKEN", description: "PAT", required: true },
    ],
  },
};

function makeIntegration(): Integration {
  return {
    name: "mygh",
    type: "github",
    credential_keys: ["GITHUB_TOKEN"],
    configured_credential_keys: ["GITHUB_TOKEN"],
    agent_count: 0,
    created_at: null,
    updated_at: null,
  };
}

describe("EditCredentialsModal", () => {
  it("disables submit when no inputs are provided", () => {
    render(
      <EditCredentialsModal
        open
        onClose={() => {}}
        onSave={() => {}}
        integration={makeIntegration()}
        integrationTypes={TYPES}
      />,
    );
    expect(
      screen.getByRole("button", { name: /Update credentials/ }),
    ).toBeDisabled();
  });

  it("submits only the credentials that have new values", () => {
    const onSave = vi.fn();
    render(
      <EditCredentialsModal
        open
        onClose={() => {}}
        onSave={onSave}
        integration={makeIntegration()}
        integrationTypes={TYPES}
      />,
    );
    const tokenLabel = screen.getByText("GITHUB_TOKEN", { exact: false });
    const input = tokenLabel.parentElement?.querySelector(
      "input",
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ghp_new" } });

    fireEvent.submit(
      screen
        .getByRole("button", { name: /Update credentials/ })
        .closest("form")!,
    );

    expect(onSave).toHaveBeenCalledWith({
      credentials: { GITHUB_TOKEN: "ghp_new" },
    });
  });

  it("shows '(set)' / '(not set)' marker based on configured_credential_keys", () => {
    const integration = makeIntegration();
    integration.configured_credential_keys = [];
    render(
      <EditCredentialsModal
        open
        onClose={() => {}}
        onSave={() => {}}
        integration={integration}
        integrationTypes={TYPES}
      />,
    );
    expect(screen.getByText("(not set)")).toBeInTheDocument();
  });
});
