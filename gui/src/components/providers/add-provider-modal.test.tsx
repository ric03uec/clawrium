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
        {children}
      </div>
    ) : null,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
}));

import { AddProviderModal } from "./add-provider-modal";
import type { ProviderTypesMap } from "@/lib/types";

const providerTypes: ProviderTypesMap = {
  openai: {
    endpoint: "https://api.openai.com/v1",
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
  ollama: {
    endpoint: null,
    models: [],
    requires_api_key: false,
    requires_endpoint: true,
  },
  bedrock: {
    endpoint: null,
    models: [
      {
        id: "claude-sonnet-4-6",
        name: "Claude Sonnet 4.6",
        lab: "Anthropic",
        context_window: 1000000,
        tags: ["chat"],
      },
    ],
    requires_api_key: false,
    requires_endpoint: false,
    requires_aws_credentials: true,
    default_region: "us-east-1",
  },
};

function renderModal(onSave: (data: unknown) => void = () => {}) {
  return render(
    <AddProviderModal
      open
      onClose={() => {}}
      onSave={onSave}
      providerTypes={providerTypes}
    />,
  );
}

describe("AddProviderModal accessibility", () => {
  it("Provider Name label is associated with its input via htmlFor", () => {
    renderModal();
    const input = screen.getByLabelText("Provider Name");
    expect(input.tagName).toBe("INPUT");
    expect(input).toHaveAttribute("type", "text");
  });

  it("Type label is associated with its select via htmlFor", () => {
    renderModal();
    const select = screen.getByLabelText("Type");
    expect(select.tagName).toBe("SELECT");
  });
});

describe("AddProviderModal bedrock branch", () => {
  it("switching type to bedrock surfaces AWS inputs and pre-fills the default region", () => {
    renderModal();
    const typeSelect = screen.getByLabelText("Type") as HTMLSelectElement;
    fireEvent.change(typeSelect, { target: { value: "bedrock" } });

    expect(screen.getByLabelText("AWS Access Key ID")).toBeTruthy();
    expect(screen.getByLabelText(/AWS Secret Access Key/)).toBeTruthy();
    const region = screen.getByLabelText("Region") as HTMLInputElement;
    expect(region.value).toBe("us-east-1");
    // API key field must be hidden in the bedrock branch.
    expect(screen.queryByLabelText("API Key")).toBeNull();
  });

  it("switching type to openai shows API key and hides AWS inputs", () => {
    renderModal();
    const typeSelect = screen.getByLabelText("Type") as HTMLSelectElement;
    fireEvent.change(typeSelect, { target: { value: "bedrock" } });
    fireEvent.change(typeSelect, { target: { value: "openai" } });

    expect(screen.getByLabelText("API Key")).toBeTruthy();
    expect(screen.queryByLabelText("AWS Access Key ID")).toBeNull();
    expect(screen.queryByLabelText(/AWS Secret Access Key/)).toBeNull();
    expect(screen.queryByLabelText("Region")).toBeNull();
  });

  it("submitting a bedrock provider sends AWS credentials and omits api_key", () => {
    const onSave = vi.fn();
    renderModal(onSave);
    fireEvent.change(screen.getByLabelText("Provider Name"), {
      target: { value: "aws-prod" },
    });
    fireEvent.change(screen.getByLabelText("Type"), {
      target: { value: "bedrock" },
    });
    fireEvent.change(screen.getByLabelText("AWS Access Key ID"), {
      target: { value: "AKIATESTING" },
    });
    fireEvent.change(screen.getByLabelText(/AWS Secret Access Key/), {
      target: { value: "topsecret" },
    });
    fireEvent.change(screen.getByLabelText("Region"), {
      target: { value: "us-west-2" },
    });

    const saveButton = screen.getByRole("button", { name: /Save/i });
    fireEvent.click(saveButton);

    expect(onSave).toHaveBeenCalledTimes(1);
    const payload = onSave.mock.calls[0][0];
    expect(payload).toMatchObject({
      name: "aws-prod",
      type: "bedrock",
      aws_access_key_id: "AKIATESTING",
      aws_secret_access_key: "topsecret",
      region: "us-west-2",
    });
    expect(payload.api_key).toBeUndefined();
  });
});
