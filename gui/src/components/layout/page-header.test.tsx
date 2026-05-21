import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PageHeader } from "./page-header";

describe("PageHeader", () => {
  it("renders the title", () => {
    render(<PageHeader title="Agents" />);
    expect(screen.getByText("Agents")).toBeInTheDocument();
  });

  it("renders the description when provided", () => {
    render(<PageHeader title="Agents" description="Manage your agents" />);
    expect(screen.getByText("Manage your agents")).toBeInTheDocument();
  });

  it("renders the Request a feature button with correct href and target", () => {
    render(<PageHeader title="Agents" />);
    const link = screen.getByRole("link", { name: /request a feature/i });
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/ric03uec/clawrium/issues/new?template=feature_request.yml",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel") ?? "").toContain("noreferrer");
  });

  it("renders external link icons (GitHub, Docs, Discord)", () => {
    render(<PageHeader title="Agents" />);
    expect(screen.getByRole("link", { name: "GitHub" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Docs" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Discord" })).toBeInTheDocument();
  });

  it("renders actions when provided", () => {
    render(
      <PageHeader
        title="Agents"
        actions={<button type="button">Add agent</button>}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Add agent" }),
    ).toBeInTheDocument();
  });
});
