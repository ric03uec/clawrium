import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Provider } from "@/lib/types";
import { ProvidersTable } from "./providers-table";

const providers: Provider[] = [
  {
    name: "local-llm",
    type: "ollama",
    endpoint: "http://10.0.0.5:11434",
    default_model: "llama3.1:8b",
    available_models: ["one", "two", "three", "four", "five", "six", "seven"],
    has_api_key: false,
    accelerator_vendor: "nvidia",
    created_at: "2026-01-02T12:00:00Z",
    updated_at: null,
  },
  {
    name: "aws-prod",
    type: "bedrock",
    endpoint: null,
    default_model: "anthropic.claude-sonnet-4-6",
    available_models: null,
    has_api_key: false,
    accelerator_vendor: null,
    region: "us-west-2",
    has_aws_credentials: true,
    created_at: null,
    updated_at: null,
  },
];

describe("ProvidersTable", () => {
  it("expands one provider at a time and preserves provider details", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <ProvidersTable
        providers={providers}
        usage={{ "local-llm": ["maurice"] }}
        onEdit={() => {}}
        onRemove={() => {}}
      />,
    );

    expect(
      container.querySelector(
        '[data-i7n-component="data-table"][data-i7n-name="providers.configured.table"]',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("2026-01-02")).toBeInTheDocument();
    expect(screen.getByText("⌀ Unassigned")).toBeInTheDocument();

    const localToggle = screen.getByRole("button", {
      name: "Expand details for local-llm",
    });
    expect(localToggle).toHaveAttribute("aria-expanded", "false");
    await user.click(localToggle);

    expect(
      screen.getByRole("button", { name: "Collapse details for local-llm" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("http://10.0.0.5:11434")).toBeInTheDocument();
    expect(screen.getByText("NVIDIA")).toBeInTheDocument();
    expect(
      screen.getByText("one, two, three, four, five, six +1 more"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("maurice")).toHaveLength(2);

    await user.click(
      screen.getByRole("button", { name: "Expand details for aws-prod" }),
    );

    expect(
      screen.getByRole("button", { name: "Expand details for local-llm" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("http://10.0.0.5:11434")).not.toBeInTheDocument();
    expect(screen.getByText("us-west-2")).toBeInTheDocument();
    expect(screen.getByText("AWS credentials")).toBeInTheDocument();
    expect(screen.getByText("configured")).toBeInTheDocument();
  });

  it("invokes only the selected nested action without toggling details", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    const onRemove = vi.fn();
    render(
      <ProvidersTable
        providers={providers}
        usage={{}}
        onEdit={onEdit}
        onRemove={onRemove}
      />,
    );

    const localRow = screen.getByRole("row", {
      name: /local-llm ollama llama3\.1:8b/,
    });
    expect(localRow).toHaveAttribute("data-row-id", "local-llm");
    await user.click(within(localRow).getByRole("button", { name: "Edit" }));

    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onEdit).toHaveBeenCalledWith(providers[0]);
    expect(onRemove).not.toHaveBeenCalled();
    expect(
      within(localRow).getByRole("button", {
        name: "Expand details for local-llm",
      }),
    ).toHaveAttribute("aria-expanded", "false");

    await user.click(within(localRow).getByRole("button", { name: "Remove" }));
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledWith(providers[0]);
    expect(onEdit).toHaveBeenCalledTimes(1);
  });
});
