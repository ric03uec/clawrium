import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import McpServersPage from "./page";

describe("MCP servers page", () => {
  it("explains that server management is for a follow-up without CRUD controls", () => {
    render(<McpServersPage />);
    expect(screen.getByRole("heading", { name: "MCP servers" })).toBeInTheDocument();
    expect(screen.getByText(/follow-up milestone/i)).toBeInTheDocument();
    expect(screen.getByText(/no create, edit, or delete actions/i)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.querySelector('[data-i7n-name="mcp-servers.page.coming-soon"]')).toBeInTheDocument();
  });
});
