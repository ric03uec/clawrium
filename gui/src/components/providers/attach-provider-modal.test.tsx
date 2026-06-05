import { render, screen, fireEvent } from "@testing-library/react";
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

import { AttachProviderModal } from "./attach-provider-modal";
import type {
  AgentAttachmentsResponse,
  Provider,
} from "@/lib/types";

const providers: Provider[] = [
  {
    name: "anth",
    type: "anthropic",
    endpoint: null,
    default_model: "claude-x",
    available_models: null,
    has_api_key: true,
    accelerator_vendor: null,
    created_at: null,
    updated_at: null,
  },
  {
    name: "openrt",
    type: "openrouter",
    endpoint: null,
    default_model: "gpt-x",
    available_models: null,
    has_api_key: true,
    accelerator_vendor: null,
    created_at: null,
    updated_at: null,
  },
];

function hermesEmpty(): AgentAttachmentsResponse {
  return {
    agent: "sage",
    agent_type: "hermes",
    supports_multi: true,
    attachments: [],
    available_roles: ["primary"],
    primary_attached: false,
    aux_count: 0,
  };
}

function hermesWithPrimary(): AgentAttachmentsResponse {
  return {
    agent: "sage",
    agent_type: "hermes",
    supports_multi: true,
    attachments: [{ name: "anth", role: "primary", model: "m" }],
    available_roles: ["vision", "web_extract", "compression"],
    primary_attached: true,
    aux_count: 0,
  };
}

function openclawEmpty(): AgentAttachmentsResponse {
  return {
    agent: "wise",
    agent_type: "openclaw",
    supports_multi: false,
    attachments: [],
    available_roles: [],
    primary_attached: false,
    aux_count: 0,
  };
}

describe("AttachProviderModal — hermes first attach", () => {
  it("pins role to primary and disables the dropdown", () => {
    render(
      <AttachProviderModal
        open
        onClose={() => {}}
        onSubmit={async () => {}}
        providers={providers}
        attachments={hermesEmpty()}
      />,
    );
    const roleSelect = screen.getByLabelText("Role") as HTMLSelectElement;
    expect(roleSelect.value).toBe("primary");
    expect(roleSelect).toBeDisabled();
    expect(roleSelect.querySelectorAll("option")).toHaveLength(1);
  });
});

describe("AttachProviderModal — hermes with primary already attached", () => {
  it("hides primary from the role list and offers aux slots", () => {
    render(
      <AttachProviderModal
        open
        onClose={() => {}}
        onSubmit={async () => {}}
        providers={providers}
        attachments={hermesWithPrimary()}
      />,
    );
    const roleSelect = screen.getByLabelText("Role") as HTMLSelectElement;
    const options = Array.from(roleSelect.querySelectorAll("option")).map(
      (o) => o.value,
    );
    expect(options).not.toContain("primary");
    expect(options).toContain("vision");
    expect(options).toContain("web_extract");
  });

  it("filters already-attached providers from the dropdown", () => {
    render(
      <AttachProviderModal
        open
        onClose={() => {}}
        onSubmit={async () => {}}
        providers={providers}
        attachments={hermesWithPrimary()}
      />,
    );
    const providerSelect = screen.getByLabelText("Provider") as HTMLSelectElement;
    const values = Array.from(providerSelect.querySelectorAll("option"))
      .map((o) => o.value)
      .filter((v) => v); // drop placeholder
    expect(values).not.toContain("anth");
    expect(values).toContain("openrt");
  });

  it("calls onSubmit with the chosen role and provider", () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <AttachProviderModal
        open
        onClose={() => {}}
        onSubmit={onSubmit}
        providers={providers}
        attachments={hermesWithPrimary()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "openrt" },
    });
    fireEvent.change(screen.getByLabelText("Role"), {
      target: { value: "vision" },
    });
    fireEvent.click(screen.getByText("Attach"));
    expect(onSubmit).toHaveBeenCalledWith("openrt", "vision");
  });
});

describe("AttachProviderModal — non-hermes agent", () => {
  it("does not render a role selector", () => {
    render(
      <AttachProviderModal
        open
        onClose={() => {}}
        onSubmit={async () => {}}
        providers={providers}
        attachments={openclawEmpty()}
      />,
    );
    expect(screen.queryByLabelText("Role")).toBeNull();
  });

  it("submits with role=null for non-hermes agents", () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <AttachProviderModal
        open
        onClose={() => {}}
        onSubmit={onSubmit}
        providers={providers}
        attachments={openclawEmpty()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "anth" },
    });
    fireEvent.click(screen.getByText("Attach"));
    expect(onSubmit).toHaveBeenCalledWith("anth", null);
  });
});

describe("AttachProviderModal — all aux slots filled", () => {
  it("surfaces a notice and disables Attach", () => {
    const filled: AgentAttachmentsResponse = {
      ...hermesWithPrimary(),
      available_roles: [],
    };
    render(
      <AttachProviderModal
        open
        onClose={() => {}}
        onSubmit={async () => {}}
        providers={providers}
        attachments={filled}
      />,
    );
    // Notice is rendered in place of the role select.
    expect(screen.queryByLabelText("Role")).toBeNull();
    // The orphaned <label htmlFor> must also be absent — otherwise AT
    // users tabbing into a stale "Role" label would focus nothing.
    // (ATX iter-3 frontend regression fix.)
    expect(screen.queryByText("Role")).toBeNull();
    expect(screen.getByText(/auxiliary slots are filled/i)).toBeTruthy();
    expect(screen.getByText("Attach")).toBeDisabled();
  });
});
