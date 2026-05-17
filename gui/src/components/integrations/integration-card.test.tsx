import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { IntegrationCard } from "./integration-card";
import type { Integration } from "@/lib/types";

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

describe("IntegrationCard", () => {
  it("shows the integration name and type", () => {
    render(
      <IntegrationCard
        integration={makeIntegration()}
        agentsUsing={0}
        onEdit={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByText("mygh")).toBeInTheDocument();
    expect(screen.getByText("github")).toBeInTheDocument();
  });

  it("renders 'credentials configured' when all required keys are set", () => {
    render(
      <IntegrationCard
        integration={makeIntegration()}
        agentsUsing={0}
        onEdit={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByText("credentials configured")).toBeInTheDocument();
  });

  it("renders 'credentials incomplete' when not all keys are set", () => {
    render(
      <IntegrationCard
        integration={makeIntegration({
          configured_credential_keys: [],
        })}
        agentsUsing={0}
        onEdit={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByText("credentials incomplete")).toBeInTheDocument();
  });

  it("shows agent usage count", () => {
    render(
      <IntegrationCard
        integration={makeIntegration()}
        agentsUsing={3}
        onEdit={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByText("3 agents")).toBeInTheDocument();
  });

  it("pluralizes correctly for one agent", () => {
    render(
      <IntegrationCard
        integration={makeIntegration()}
        agentsUsing={1}
        onEdit={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByText("1 agent")).toBeInTheDocument();
  });

  it("invokes onEdit when edit button clicked", () => {
    const onEdit = vi.fn();
    render(
      <IntegrationCard
        integration={makeIntegration()}
        agentsUsing={0}
        onEdit={onEdit}
        onRemove={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Edit credentials"));
    expect(onEdit).toHaveBeenCalled();
  });

  it("invokes onRemove when remove button clicked", () => {
    const onRemove = vi.fn();
    render(
      <IntegrationCard
        integration={makeIntegration()}
        agentsUsing={0}
        onEdit={() => {}}
        onRemove={onRemove}
      />,
    );
    fireEvent.click(screen.getByText("Remove"));
    expect(onRemove).toHaveBeenCalled();
  });
});
