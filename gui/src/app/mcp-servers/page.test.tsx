import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import McpServersPage from "./page";

vi.mock("@/components/layout", () => ({ PageHeader: ({ title }: { title: string }) => <h1>{title}</h1> }));

describe("MCP servers page", () => {
  it("explains that server management is for a follow-up without CRUD controls", () => {
    render(<McpServersPage />);
    expect(screen.getByRole("heading", { name: "MCP servers" })).toBeInTheDocument();
    expect(screen.getByText(/follow-up milestone/i)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
