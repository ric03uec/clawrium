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

import {
  AddIntegrationModal,
  isSecretKey,
} from "./add-integration-modal";
import type { IntegrationTypesMap } from "@/lib/types";

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
  atlassian: {
    description: "Atlassian Cloud",
    credentials: [
      {
        key: "ATLASSIAN_URL",
        description: "Instance URL",
        required: true,
      },
      {
        key: "ATLASSIAN_EMAIL",
        description: "Email",
        required: true,
      },
      {
        key: "ATLASSIAN_API_TOKEN",
        description: "API Token",
        required: true,
      },
      {
        key: "CONFLUENCE_SPACES_FILTER",
        description: "Optional filter",
        required: false,
      },
    ],
  },
};

describe("isSecretKey", () => {
  it.each([
    ["GITHUB_TOKEN", true],
    ["LINEAR_API_KEY", true],
    ["ATLASSIAN_API_TOKEN", true],
    ["GITLAB_SECRET", true],
    ["NOTION_PASSWORD", true],
    ["ATLASSIAN_URL", false],
    ["ATLASSIAN_EMAIL", false],
    ["CONFLUENCE_SPACES_FILTER", false],
  ])("matches %s -> %s", (key, expected) => {
    expect(isSecretKey(key)).toBe(expected);
  });
});

describe("AddIntegrationModal", () => {
  function setup(extra: Partial<Parameters<typeof AddIntegrationModal>[0]> = {}) {
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(
      <AddIntegrationModal
        open
        onClose={onClose}
        onSave={onSave}
        integrationTypes={TYPES}
        {...extra}
      />,
    );
    return { onSave, onClose };
  }

  it("renders an option for each integration type", () => {
    setup();
    expect(
      screen.getByRole("option", { name: "github" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "atlassian" }),
    ).toBeInTheDocument();
  });

  it("renders dynamic credential fields after a type is selected", () => {
    setup();
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "atlassian" },
    });
    expect(screen.getByText("ATLASSIAN_URL")).toBeInTheDocument();
    expect(screen.getByText("ATLASSIAN_EMAIL")).toBeInTheDocument();
    expect(screen.getByText("ATLASSIAN_API_TOKEN")).toBeInTheDocument();
    expect(screen.getByText("CONFLUENCE_SPACES_FILTER")).toBeInTheDocument();
  });

  it("renders password inputs for secret-style keys and text inputs otherwise", () => {
    setup();
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "atlassian" },
    });

    const tokenLabel = screen.getByText("ATLASSIAN_API_TOKEN");
    const tokenInput = tokenLabel.parentElement?.querySelector("input");
    expect(tokenInput?.getAttribute("type")).toBe("password");

    const emailLabel = screen.getByText("ATLASSIAN_EMAIL");
    const emailInput = emailLabel.parentElement?.querySelector("input");
    expect(emailInput?.getAttribute("type")).toBe("text");
  });

  it("disables Save when required credentials are missing", () => {
    setup();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "my-gh" },
    });
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "github" },
    });
    const save = screen.getByRole("button", { name: /Save/ });
    expect(save).toBeDisabled();
  });

  it("submits collected credentials when all required values present", () => {
    const { onSave } = setup();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "my-gh" },
    });
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "github" },
    });

    const tokenLabel = screen.getByText("GITHUB_TOKEN");
    const tokenInput = tokenLabel.parentElement?.querySelector(
      "input",
    ) as HTMLInputElement;
    fireEvent.change(tokenInput, { target: { value: "ghp_xxx" } });

    fireEvent.submit(screen.getByRole("button", { name: /Save/ }).closest("form")!);

    expect(onSave).toHaveBeenCalledWith({
      name: "my-gh",
      type: "github",
      credentials: { GITHUB_TOKEN: "ghp_xxx" },
    });
  });
});
