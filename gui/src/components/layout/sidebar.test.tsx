import { render, screen, waitFor, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
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

  it("places Skills and Integrations between Providers and Settings", async () => {
    await renderAndFlush();
    const labels = screen
      .getAllByRole("link")
      .map((el) => el.textContent?.trim())
      .filter(
        (t) =>
          t && ["Providers", "Skills", "Integrations", "Settings"].includes(t),
      );
    expect(labels).toEqual([
      "Providers",
      "Skills",
      "Integrations",
      "Settings",
    ]);
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
});
