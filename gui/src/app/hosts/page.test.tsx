import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HostsPage from "./page";

describe("Hosts placeholder", () => {
  it("links to the existing topology view", () => {
    render(<HostsPage />);
    expect(screen.getByRole("heading", { name: "Hosts" })).toBeInTheDocument();
    expect(screen.getByText(/planned for a later delivery step/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open topology" })).toHaveAttribute("href", "/topology");
    expect(document.querySelector('[data-i7n-name="hosts.page.coming-soon"]')).toBeInTheDocument();
  });
});
