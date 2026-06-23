import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IntegrationIcon } from "./integration-icon";

const VENDORS: Array<[string, string]> = [
  ["github", "/integration-icons/github.svg"],
  ["gitlab", "/integration-icons/gitlab.svg"],
  ["atlassian", "/integration-icons/atlassian.svg"],
  ["linear", "/integration-icons/linear.svg"],
  ["notion", "/integration-icons/notion.svg"],
  ["brave", "/integration-icons/brave.svg"],
  ["git", "/integration-icons/git.svg"],
];

describe("IntegrationIcon", () => {
  it.each(VENDORS)(
    "renders the official icon for %s",
    (type, expectedSrc) => {
      const { container } = render(<IntegrationIcon type={type} />);
      const img = container.querySelector("img");
      expect(img).not.toBeNull();
      expect(img).toHaveAttribute("src", expectedSrc);
    },
  );

  it("marks the rendered SVG as decorative (alt='' + aria-hidden)", () => {
    const { container } = render(<IntegrationIcon type="github" />);
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveAttribute("aria-hidden", "true");
  });

  it("applies size to width/height and uses lazy loading", () => {
    const { container } = render(<IntegrationIcon type="github" size={32} />);
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("width", "32");
    expect(img).toHaveAttribute("height", "32");
    expect(img).toHaveAttribute("loading", "lazy");
  });

  it.each([
    ["custom", "cu"],
    ["x", "x"],
    ["", ""],
  ])("falls back to a label for unknown type %p", (type, expectedLabel) => {
    const { container } = render(<IntegrationIcon type={type} />);
    expect(container.querySelector("img")).toBeNull();
    const fallback = container.querySelector(
      '[data-testid="integration-icon-fallback"]',
    );
    expect(fallback).not.toBeNull();
    expect(fallback).toHaveAttribute("aria-hidden", "true");
    // toHaveTextContent('') is a substring match — it would pass against
    // ANY textContent. Pin the exact string instead.
    expect(fallback?.textContent).toBe(expectedLabel);
  });

  it("passes className through and respects size on the fallback", () => {
    const { container } = render(
      <IntegrationIcon type="unknown" size={40} className="ring-1" />,
    );
    const fallback = container.querySelector(
      '[data-testid="integration-icon-fallback"]',
    ) as HTMLElement;
    expect(fallback).not.toBeNull();
    expect(fallback.className).toContain("ring-1");
    expect(fallback.style.width).toBe("40px");
    expect(fallback.style.height).toBe("40px");
  });
});
