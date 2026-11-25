import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import HostsPage from "./page";

vi.mock("@/components/layout", () => ({ PageHeader: ({ title }: { title: string }) => <h1>{title}</h1> }));

describe("Hosts placeholder", () => {
  it("links to the existing topology view", () => {
    render(<HostsPage />);
    expect(screen.getByRole("heading", { name: "Hosts" })).toBeInTheDocument();
    expect(screen.getByText(/planned for a later delivery step/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open topology" })).toHaveAttribute("href", "/topology");
  });
});
