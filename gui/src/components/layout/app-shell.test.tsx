import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./app-shell";

vi.mock("./sidebar", () => ({ Sidebar: () => <aside className="app-sidebar">Sidebar</aside> }));

describe("AppShell", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: async () => ({}) })));
  afterEach(() => vi.unstubAllGlobals());
  it("places page content within the app grid, header, and footer", () => {
    const { container } = render(<AppShell><p>Page content</p></AppShell>);
    expect(container.querySelector(".app-root .app-sidebar")).toBeInTheDocument();
    expect(container.querySelector(".app-root .app-main .app-header")).toBeInTheDocument();
    expect(container.querySelector(".app-root .app-main .app-page")).toContainElement(screen.getByText("Page content"));
    expect(container.querySelector(".app-root .app-main .app-footer")).toBeInTheDocument();
  });
  it("loads and displays the version, aborting on unmount", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ json: async () => ({ version: "1.2.3" }) });
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = render(<AppShell>Content</AppShell>);
    expect(await screen.findByText("v1.2.3")).toBeInTheDocument();
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/settings/version");
    const signal = options.signal as AbortSignal;
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });
  it("keeps the footer usable if fetching the version fails", async () => {
    let rejectFetch!: (error: Error) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise((_resolve, reject) => { rejectFetch = reject; })));
    render(<AppShell>Content</AppShell>);
    await act(async () => { rejectFetch(new Error("unavailable")); });
    expect(screen.getByRole("link", { name: "Documentation" })).toBeInTheDocument();
    expect(screen.queryByText(/^v\d/)).not.toBeInTheDocument();
  });
  it("handles a missing version and malformed JSON", async () => {
    for (const json of [async () => ({}), async () => { throw new Error("bad JSON"); }]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json }));
      const { unmount } = render(<AppShell>Content</AppShell>);
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByRole("link", { name: "Documentation" })).toBeInTheDocument();
      expect(screen.queryByText(/^v\d/)).not.toBeInTheDocument();
      unmount();
    }
  });
});
