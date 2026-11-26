import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./sidebar";

const pathnameRef = { current: "/" };

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameRef.current,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
  } & React.HTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

function mockFetch(impl: typeof fetch) {
  vi.stubGlobal("fetch", impl);
}

async function renderAndFlush() {
  const result = render(<Sidebar />);
  await waitFor(() => expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument());
  return result;
}

describe("Sidebar", () => {
  beforeEach(() => {
    pathnameRef.current = "/";
    mockFetch(
      vi.fn().mockResolvedValue({
        json: () => Promise.resolve({ version: "" }),
      }) as unknown as typeof fetch,
    );
  });

  it("renders the approved primary hierarchy in exact order", async () => {
    await renderAndFlush();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getAllByRole("link").map((link) => link.textContent?.trim())).toEqual([
      "Dashboard",
      "Agents",
      "Hosts",
      "Providers",
      "Integrations",
      "MCP servers",
    ]);
    expect(within(nav).getByText("Main")).toBeInTheDocument();
    expect(within(nav).getByText("Configuration")).toBeInTheDocument();
  });

  it("removes unapproved stubs and does not render a coming-soon modal", async () => {
    await renderAndFlush();
    expect(screen.queryByText("Scheduled Jobs")).not.toBeInTheDocument();
    expect(screen.queryByText("Agent Builder")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("links MCP servers to its dedicated page without a modal trigger", async () => {
    await renderAndFlush();
    expect(screen.getByRole("link", { name: "MCP servers" })).toHaveAttribute("href", "/mcp-servers");
    expect(screen.queryByRole("button", { name: /MCP servers/i })).not.toBeInTheDocument();
  });

  it("keeps Topology and Skills in an explicitly labeled transitional landmark", async () => {
    await renderAndFlush();
    const primary = screen.getByRole("navigation", { name: "Main navigation" });
    const transitional = screen.getByRole("navigation", { name: "Transitional navigation" });
    expect(within(primary).queryByRole("link", { name: "Topology" })).not.toBeInTheDocument();
    expect(within(primary).queryByRole("link", { name: "Skills" })).not.toBeInTheDocument();
    expect(within(transitional).getByText("Transitional pages")).toBeInTheDocument();
    expect(within(transitional).getAllByRole("link").map((link) => link.textContent)).toEqual(["Topology", "Skills"]);
  });

  it.each([
    ["/hosts", "Hosts"],
    ["/hosts/server-a", "Hosts"],
    ["/mcp-servers", "MCP servers"],
    ["/mcp-servers/example", "MCP servers"],
    ["/topology", "Topology"],
    ["/skills/catalog", "Skills"],
  ])("marks %s active on the matching exact or nested route", async (pathname, label) => {
    pathnameRef.current = pathname;
    await renderAndFlush();
    expect(screen.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
  });

  it.each([
    ["/hosts-legacy", "Hosts"],
    ["/mcp-servers-old", "MCP servers"],
    ["/providers-legacy", "Providers"],
  ])("does not activate %s routes that only share a prefix", async (pathname, label) => {
    pathnameRef.current = pathname;
    await renderAndFlush();
    expect(screen.getByRole("link", { name: label })).not.toHaveAttribute("aria-current");
  });

  it("only activates Dashboard at the root", async () => {
    pathnameRef.current = "/agents";
    await renderAndFlush();
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("marks nested Settings routes active outside primary navigation", async () => {
    pathnameRef.current = "/settings/profile";
    await renderAndFlush();
    const primary = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(primary).queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  });

  it("keeps only Settings and GitHub as sidebar footer links", async () => {
    const { container } = await renderAndFlush();
    const footer = container.querySelector(".sidebar-footer");
    expect(footer).not.toBeNull();
    expect(within(footer as HTMLElement).getAllByRole("link").map((link) => link.textContent?.trim())).toEqual([
      "Settings",
      "GitHub",
    ]);
    const github = within(footer as HTMLElement).getByRole("link", { name: "GitHub" });
    expect(github).toHaveAttribute("href", "https://github.com/ric03uec/clawrium");
    expect(github).toHaveAttribute("target", "_blank");
    expect(screen.queryByRole("link", { name: "Docs" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Discord" })).not.toBeInTheDocument();
  });

  it("collapses accessibly, keeps the toggle focused, and expands again", async () => {
    await renderAndFlush();
    const sidebar = screen.getByRole("complementary", { name: "Fleet navigation" });
    const collapse = screen.getByRole("button", { name: "Collapse sidebar" });
    collapse.focus();
    fireEvent.click(collapse);
    expect(sidebar).toHaveClass("sidebar-collapsed");
    const expand = screen.getByRole("button", { name: "Expand sidebar" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(expand);
    fireEvent.click(expand);
    expect(sidebar).not.toHaveClass("sidebar-collapsed");
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toHaveAttribute("aria-expanded", "true");
  });

  it("renders the Clawrium wordmark with a single accessible name", async () => {
    await renderAndFlush();
    const link = screen.getByRole("link", { name: "Clawrium" });
    expect(link.querySelector("img")).toHaveAttribute("alt", "");
    expect(link.querySelector("img")).toHaveAttribute("aria-hidden", "true");
  });

  it("renders a fetched version and accepts a supplied version without another request", async () => {
    mockFetch(
      vi.fn().mockResolvedValue({
        json: () => Promise.resolve({ version: "1.2.3" }),
      }) as unknown as typeof fetch,
    );
    const { unmount } = render(<Sidebar />);
    expect(await screen.findByText("v1.2.3")).toBeInTheDocument();
    unmount();

    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<Sidebar version="2.3.4" />);
    expect(screen.getByText("v2.3.4")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uses an AbortSignal and aborts the version request on unmount", async () => {
    const fetchMock = vi.fn().mockReturnValue(new Promise(() => {})) as unknown as typeof fetch;
    mockFetch(fetchMock);
    const { unmount } = render(<Sidebar />);
    const [, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(init.signal.aborted).toBe(false);
    unmount();
    expect(init.signal.aborted).toBe(true);
  });

  it("handles version failures without crashing or showing a false value", async () => {
    mockFetch(vi.fn().mockRejectedValue(new Error("boom")) as unknown as typeof fetch);
    render(<Sidebar />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.queryByText(/^v/)).not.toBeInTheDocument();
  });
});
