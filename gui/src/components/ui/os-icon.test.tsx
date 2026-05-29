import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OSIcon } from "./os-icon";

describe("OSIcon", () => {
  it("renders nothing for a null os_family", () => {
    const { container } = render(<OSIcon os={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the macOS chip with image + label", () => {
    const { container } = render(<OSIcon os="darwin" variant="chip" />);
    expect(screen.getByLabelText("macOS")).toBeInTheDocument();
    const img = container.querySelector("img");
    expect(img).toBeTruthy();
    expect(img?.getAttribute("src")).toBe("/os-icons/macos.jpg");
    expect(img?.getAttribute("alt")).toBe("macOS");
    const labelSpan = container.querySelector("span > span");
    expect(labelSpan?.textContent).toBe("macOS");
  });

  it("renders the Linux chip with image + label", () => {
    const { container } = render(<OSIcon os="linux" variant="chip" />);
    expect(screen.getByLabelText("Linux")).toBeInTheDocument();
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("/os-icons/linux.png");
    expect(img?.getAttribute("alt")).toBe("Linux");
  });

  it("dot variant renders only the icon image (no label span)", () => {
    const { container } = render(<OSIcon os="darwin" variant="dot" />);
    expect(container.querySelector("img")).toBeTruthy();
    expect(container.querySelectorAll("span > span").length).toBe(0);
  });

  it("respects custom size", () => {
    const { container } = render(<OSIcon os="darwin" size={32} />);
    const img = container.querySelector("img");
    expect(img?.getAttribute("width")).toBe("32");
    expect(img?.getAttribute("height")).toBe("32");
  });
});
