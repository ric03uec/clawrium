import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./sidebar";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("next/link", () => ({ default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a> }));

describe("milestone navigation", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: () => Promise.resolve({ version: "1.0" }) })));
  it("exposes ordered primary destinations and an MCP page rather than a modal", async () => {
    const { container } = render(<Sidebar />);
    await screen.findByText("v1.0");
    expect(container.querySelector(".ds-app-sidebar-brand")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual(["Dashboard", "Agents", "Hosts", "Providers", "Integrations", "MCP servers"]);
    expect(within(nav).getByRole("link", { name: "MCP servers" })).toHaveAttribute("href", "/mcp-servers");
  });
  it("keeps the navigation landmark while collapsing and expanding", async () => {
    render(<Sidebar />);
    await screen.findByText("v1.0");
    const sidebar = screen.getByRole("complementary", { name: "Fleet navigation" });
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(sidebar).toHaveClass("ds-app-sidebar", "sidebar-collapsed");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(sidebar).toHaveClass("ds-app-sidebar");
    expect(sidebar).not.toHaveClass("sidebar-collapsed");
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toHaveAttribute("aria-expanded", "true");
  });
});
