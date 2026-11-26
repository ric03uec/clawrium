import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/hosts", () => ({
  HostTable: () => <div data-testid="host-table">Fleet Hosts</div>,
}));

import HostsPage from "./page";

describe("Hosts page", () => {
  it("renders the real hosts inventory instead of a placeholder", () => {
    render(<HostsPage />);
    expect(screen.getByRole("heading", { name: "Hosts" })).toBeInTheDocument();
    expect(screen.getByTestId("host-table")).toBeInTheDocument();
    expect(screen.queryByText(/planned for a later delivery step/i)).not.toBeInTheDocument();
    expect(document.querySelector('[data-i7n-name="hosts.page.header"]')).toBeInTheDocument();
  });
});
