import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./app-shell";

vi.mock("./sidebar", () => ({
  Sidebar: ({ version }: { version?: string }) => (
    <aside className="app-sidebar" data-version={version}>Sidebar</aside>
  ),
}));

describe("AppShell", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: async () => ({}) })));
  afterEach(() => vi.unstubAllGlobals());

  it("places page content within the shell and grid backdrop", () => {
    const { container } = render(<AppShell><p>Page content</p></AppShell>);
    expect(container.querySelector(".app-root .app-sidebar")).toBeInTheDocument();
    expect(container.querySelector(".app-root .app-main .app-header")).toBeInTheDocument();
    expect(container.querySelector(".app-root .app-main .app-page.ds-grid-backdrop")).toContainElement(screen.getByText("Page content"));
    expect(container.querySelector(".app-root .app-main .app-footer")).toBeInTheDocument();
    expect(container.querySelector(".iteration-design-system")).not.toBeInTheDocument();
  });

  it("renders intentional global chrome without duplicating sidebar GitHub content", () => {
    render(<AppShell>Content</AppShell>);
    const header = screen.getByRole("banner", { name: "Application header" });
    expect(within(header).getByText("Fleet workspace")).toBeInTheDocument();
    expect(within(header).getByText("Manage agents across your network")).toBeInTheDocument();
    expect(within(header).getByRole("link", { name: "Documentation" })).toHaveAttribute("href", "https://ric03uec.github.io/clawrium/");
    expect(within(header).getByRole("link", { name: "Request a feature" })).toBeInTheDocument();
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByRole("link", { name: "Documentation" })).toBeInTheDocument();
    expect(within(footer).queryByRole("link", { name: "GitHub" })).not.toBeInTheDocument();
  });

  it("loads the version once for the sidebar and aborts on unmount", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ json: async () => ({ version: "1.2.3" }) });
    vi.stubGlobal("fetch", fetchMock);
    const { container, unmount } = render(<AppShell>Content</AppShell>);
    await waitFor(() => expect(container.querySelector(".app-sidebar")).toHaveAttribute("data-version", "1.2.3"));
    expect(screen.getByRole("contentinfo")).toHaveTextContent("v1.2.3");
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/settings/version");
    const signal = options.signal as AbortSignal;
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it("places a keyboard-first skip link before the sidebar and focuses main content", async () => {
    const user = userEvent.setup();
    render(<AppShell>Content</AppShell>);

    await user.tab();
    const skipLink = screen.getByRole("link", { name: "Skip to main content" });
    expect(skipLink).toHaveFocus();
    expect(skipLink).toHaveAttribute("href", "#main-content");
    await user.keyboard("{Enter}");
    expect(screen.getByRole("main")).toHaveFocus();
    expect(screen.getByRole("main")).toHaveAttribute("tabindex", "-1");
  });

  it("keeps the footer usable if fetching the version fails", async () => {
    let rejectFetch!: (error: Error) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise((_resolve, reject) => { rejectFetch = reject; })));
    render(<AppShell>Content</AppShell>);
    await act(async () => { rejectFetch(new Error("unavailable")); });
    expect(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Documentation" })).toBeInTheDocument();
  });

  it("handles a missing version and malformed JSON", async () => {
    for (const json of [async () => ({}), async () => { throw new Error("bad JSON"); }]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json }));
      const { container, unmount } = render(<AppShell>Content</AppShell>);
      await act(async () => { await Promise.resolve(); });
      expect(container.querySelector(".app-sidebar")).toHaveAttribute("data-version", "");
      expect(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Documentation" })).toBeInTheDocument();
      unmount();
    }
  });
});
