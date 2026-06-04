import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("@/styles/globals.css", () => ({}));

vi.mock("./providers", () => ({
  Providers: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="providers-wrapper">{children}</div>
  ),
}));

vi.mock("@/components/layout", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="shell-wrapper">{children}</div>
  ),
}));

import RootLayout, { metadata } from "./layout";

describe("RootLayout", () => {
  beforeEach(() => {
    // RootLayout renders <html><body>...</body></html>; jsdom logs a noisy
    // warning when those nest inside <body>. The behavior we care about is
    // the children pipeline, not the surrounding html.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("forwards children through Providers and AppShell", () => {
    render(
      <RootLayout>
        <p data-testid="child">hello</p>
      </RootLayout>,
    );

    const providers = screen.getByTestId("providers-wrapper");
    const shell = screen.getByTestId("shell-wrapper");
    const child = screen.getByTestId("child");

    expect(providers).toContainElement(shell);
    expect(shell).toContainElement(child);
    expect(child).toHaveTextContent("hello");
  });

  it("renders the html root with lang=\"en\"", () => {
    const { baseElement } = render(
      <RootLayout>
        <span />
      </RootLayout>,
    );

    const html = baseElement.querySelector("html");
    expect(html).not.toBeNull();
    expect(html?.getAttribute("lang")).toBe("en");
  });

  it("exposes the page metadata expected by Next.js", () => {
    expect(metadata.title).toBe("Clawrium");
    expect(metadata.icons).toMatchObject({
      icon: "/clawrium-logo.png",
      shortcut: "/clawrium-logo.png",
      apple: "/clawrium-logo.png",
    });
  });
});
