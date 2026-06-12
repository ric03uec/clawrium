import {
  render,
  screen,
  waitFor,
  act,
  within,
  fireEvent,
} from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { Sidebar } from "./sidebar";

const pathnameRef = { current: "/" };

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameRef.current,
}));

// jsdom does not implement HTMLDialogElement.showModal / close. The stub
// flips an "open" attribute so role="dialog" queries work the same way
// browsers expose it. Mirrors the shim in modal.test.tsx; needed here so
// tests that open the ComingSoonModal don't throw "Not implemented".
beforeEach(() => {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function showModal(
      this: HTMLDialogElement,
    ) {
      this.setAttribute("open", "");
    };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function close(
      this: HTMLDialogElement,
    ) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    };
  }
});

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

function mockFetchOnce(impl: typeof fetch) {
  vi.stubGlobal("fetch", impl);
}

describe("Sidebar", () => {
  beforeEach(() => {
    pathnameRef.current = "/";
    mockFetchOnce(
      vi.fn().mockResolvedValue({
        json: () => Promise.resolve({ version: "" }),
      }) as unknown as typeof fetch,
    );
  });

  async function renderAndFlush() {
    const result = render(<Sidebar />);
    await waitFor(() => {
      expect(screen.getByRole("navigation")).toBeInTheDocument();
    });
    return result;
  }

  it("renders every top-level nav item", async () => {
    await renderAndFlush();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agents" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Topology" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Providers" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Integrations" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("renders the Clawrium wordmark with a decorative logo (single a11y name)", async () => {
    await renderAndFlush();
    // Link's accessible name comes from the wordmark span only — the logo
    // is alt="" + aria-hidden so screen readers do not double-announce.
    const link = screen.getByRole("link", { name: "Clawrium" });
    expect(link).toBeInTheDocument();
    const img = link.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("alt")).toBe("");
    expect(img?.getAttribute("aria-hidden")).toBe("true");
  });

  it("preserves the canonical link order Dashboard → Agents → Topology → Providers → Skills → Integrations → Settings", async () => {
    // ATX-4 W3: the previous ordering test only checked four labels and
    // missed the new Agents row entirely. Lock in the full main-nav
    // sequence plus the footer Settings link, in document order.
    await renderAndFlush();
    const expected = [
      "Dashboard",
      "Agents",
      "Topology",
      "Providers",
      "Skills",
      "Integrations",
      "Settings",
    ];
    const labels = screen
      .getAllByRole("link")
      .map((el) => el.textContent?.trim())
      .filter((t) => t && expected.includes(t));
    expect(labels).toEqual(expected);
  });

  it("labels the nav for assistive tech", async () => {
    await renderAndFlush();
    expect(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).toBeInTheDocument();
  });

  it("marks only the matching nav item as current on exact match", async () => {
    pathnameRef.current = "/providers";
    await renderAndFlush();
    expect(
      screen.getByRole("link", { name: "Providers" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("link", { name: "Topology" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("activates parent route on nested path", async () => {
    pathnameRef.current = "/providers/openai";
    await renderAndFlush();
    expect(
      screen.getByRole("link", { name: "Providers" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("does not activate parent on a sibling path that shares a prefix", async () => {
    pathnameRef.current = "/providers-legacy";
    await renderAndFlush();
    expect(
      screen.getByRole("link", { name: "Providers" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("does not activate Dashboard on non-root paths", async () => {
    pathnameRef.current = "/topology";
    await renderAndFlush();
    expect(
      screen.getByRole("link", { name: "Dashboard" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("renders the version footer when the fetch resolves with a version", async () => {
    mockFetchOnce(
      vi.fn().mockResolvedValue({
        json: () => Promise.resolve({ version: "1.2.3" }),
      }) as unknown as typeof fetch,
    );
    render(<Sidebar />);
    await waitFor(() => {
      expect(screen.getByText("v1.2.3")).toBeInTheDocument();
    });
  });

  it("leaves the footer empty (no crash) when the fetch rejects", async () => {
    mockFetchOnce(
      vi.fn().mockRejectedValue(new Error("boom")) as unknown as typeof fetch,
    );
    expect(() => render(<Sidebar />)).not.toThrow();
    await waitFor(() => {
      expect(screen.queryByText(/^v/)).not.toBeInTheDocument();
    });
  });

  it("calls /api/settings/version with an AbortSignal", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      json: () => Promise.resolve({ version: "9.9.9" }),
    }) as unknown as typeof fetch;
    mockFetchOnce(fetchMock);

    render(<Sidebar />);
    await waitFor(() => {
      expect(screen.getByText("v9.9.9")).toBeInTheDocument();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(url).toBe("/api/settings/version");
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("aborts the in-flight request on unmount", async () => {
    const abortSpy = vi.spyOn(AbortController.prototype, "abort");
    // Fetch that never settles — the only way the test ends cleanly is via abort.
    mockFetchOnce(
      vi.fn().mockReturnValue(new Promise(() => {})) as unknown as typeof fetch,
    );

    const { unmount } = render(<Sidebar />);
    unmount();

    expect(abortSpy).toHaveBeenCalledTimes(1);
  });

  it("renders GitHub, Docs, and Discord links in the footer with target=_blank", async () => {
    await renderAndFlush();
    const github = screen.getByRole("link", { name: "GitHub" });
    const docs = screen.getByRole("link", { name: "Docs" });
    const discord = screen.getByRole("link", { name: "Discord" });

    expect(github).toHaveAttribute("href", "https://github.com/ric03uec/clawrium");
    expect(docs).toHaveAttribute("href", "https://ric03uec.github.io/clawrium/");
    expect(discord).toHaveAttribute("href", "https://discord.gg/KzPuSxgQ98");

    for (const link of [github, docs, discord]) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel") ?? "").toContain("noreferrer");
    }
  });

  it("suppresses AbortError without clobbering version state", async () => {
    const abortErr = new Error("aborted");
    abortErr.name = "AbortError";
    mockFetchOnce(
      vi.fn().mockRejectedValue(abortErr) as unknown as typeof fetch,
    );

    render(<Sidebar />);
    // Let microtasks settle so the rejection handler runs.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // setVersion('') would render an empty <span>; the suppression branch must
    // leave version as null so the placeholder space renders instead.
    expect(screen.queryByText(/^v/)).not.toBeInTheDocument();
  });

  // W2: previous ordering test passed only because the footer follows the
  // main nav in DOM order. The semantic guarantee is that Settings lives
  // OUTSIDE the main-nav landmark — that's what we lock in here.
  it("renders Settings outside the main-nav landmark", async () => {
    await renderAndFlush();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(
      within(nav).queryByRole("link", { name: "Settings" }),
    ).toBeNull();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  // W3: Settings active state — covers the footer Link's aria-current
  // wiring on exact match, nested path, and negative.
  it("marks footer Settings link as current on /settings", async () => {
    pathnameRef.current = "/settings";
    await renderAndFlush();
    expect(
      screen.getByRole("link", { name: "Settings" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("marks footer Settings link as current on nested /settings/profile", async () => {
    pathnameRef.current = "/settings/profile";
    await renderAndFlush();
    expect(
      screen.getByRole("link", { name: "Settings" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("does not mark footer Settings link as current on root path", async () => {
    pathnameRef.current = "/";
    await renderAndFlush();
    expect(
      screen.getByRole("link", { name: "Settings" }),
    ).not.toHaveAttribute("aria-current");
  });

  // W4: Stub rows render as <button> (not <a>) and clicking them opens
  // the ComingSoonModal with the matching feature name + upvote URL.
  it("renders MCPs / Scheduled Jobs / Agent Builder as buttons, not links", async () => {
    await renderAndFlush();
    for (const label of ["MCPs", "Scheduled Jobs", "Agent Builder"]) {
      expect(
        screen.getByRole("button", { name: `${label} — coming soon` }),
      ).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: label })).toBeNull();
    }
  });

  it("clicking MCPs opens the coming-soon modal targeting issue #698", async () => {
    await renderAndFlush();
    fireEvent.click(
      screen.getByRole("button", { name: "MCPs — coming soon" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("MCPs — coming soon")).toBeVisible();
    const upvote = within(dialog).getByRole("link", {
      name: "Upvote MCPs on GitHub",
    });
    expect(upvote).toHaveAttribute(
      "href",
      "https://github.com/ric03uec/clawrium/issues/698",
    );
  });

  it("clicking Scheduled Jobs opens the modal targeting issue #699", async () => {
    await renderAndFlush();
    fireEvent.click(
      screen.getByRole("button", { name: "Scheduled Jobs — coming soon" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Scheduled Jobs — coming soon"),
    ).toBeVisible();
    expect(
      within(dialog).getByRole("link", {
        name: "Upvote Scheduled Jobs on GitHub",
      }),
    ).toHaveAttribute(
      "href",
      "https://github.com/ric03uec/clawrium/issues/699",
    );
  });

  it("clicking Agent Builder opens the modal targeting issue #700", async () => {
    await renderAndFlush();
    fireEvent.click(
      screen.getByRole("button", { name: "Agent Builder — coming soon" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Agent Builder — coming soon"),
    ).toBeVisible();
    expect(
      within(dialog).getByRole("link", {
        name: "Upvote Agent Builder on GitHub",
      }),
    ).toHaveAttribute(
      "href",
      "https://github.com/ric03uec/clawrium/issues/700",
    );
  });

  // W1: closing the modal must restore focus to the button that opened it
  // (WCAG 2.4.3). Sidebar refocuses synchronously in closeStub. We trigger
  // close via the modal's ✕ button (a React onClick path), since that
  // matches how a real user clicks Close / X — and unlike a raw
  // dialog.dispatchEvent('close'), it goes through act() automatically.
  it("restores focus to the triggering stub button on modal close", async () => {
    await renderAndFlush();
    const trigger = screen.getByRole("button", {
      name: "MCPs — coming soon",
    });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    const closeX = within(dialog).getByRole("button", { name: "Close dialog" });
    fireEvent.click(closeX);
    expect(document.activeElement).toBe(trigger);
  });
});
