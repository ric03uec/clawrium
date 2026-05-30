import { render, screen } from "@testing-library/react";
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
};

function renderModal() {
  return render(
    <AddProviderModal
      open
      onClose={() => {}}
      onSave={() => {}}
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
