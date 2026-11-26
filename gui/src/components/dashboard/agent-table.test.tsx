import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FleetResponse } from "@/lib/types";

const mocks = vi.hoisted(() => ({
  useFleetHealth: vi.fn(),
  fleetState: {
    data: undefined as FleetResponse | undefined,
    isLoading: false,
  },
}));

vi.mock("@/hooks", () => ({
  useFleet: () => mocks.fleetState,
  useFleetHealth: mocks.useFleetHealth,
}));

import { AgentTable } from "./agent-table";

const fleet: FleetResponse = {
  agents: [
    {
      agent_key: "lab-host::zeroclaw::primary",
      agent_name: "primary",
      agent_type: "zeroclaw",
      host: "192.0.2.10",
      host_alias: "lab-host",
      host_os_family: "linux",
      status: "running",
      model: "",
      uptime: "",
      gateway_url: null,
      provider: "openai",
      provider_type: "openai",
    },
  ],
  summary: { total: 1, running: 1, provisioning: 0, hosts: 1 },
};

describe("AgentTable", () => {
  beforeEach(() => {
    mocks.useFleetHealth.mockReset();
    mocks.fleetState.data = undefined;
    mocks.fleetState.isLoading = false;
  });

  it("preserves health polling and renders loading and empty states semantically", () => {
    mocks.fleetState.isLoading = true;
    const { rerender } = render(<AgentTable />);

    expect(mocks.useFleetHealth).toHaveBeenCalledOnce();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByLabelText("Fleet Agents")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("cell", { name: "Loading..." })).toBeInTheDocument();

    mocks.fleetState.isLoading = false;
    rerender(<AgentTable />);
    expect(screen.getByRole("cell", { name: "No agents installed yet" })).toBeInTheDocument();
    expect(screen.getByText("0 agents")).toBeInTheDocument();
  });

  it("renders every agent column and fallback through DataTable", () => {
    mocks.fleetState.data = fleet;
    const { container } = render(<AgentTable />);

    expect(container.querySelector('[data-i7n-component="data-table"][data-i7n-name="dashboard.agents.table-card"]')).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    for (const heading of ["Name", "Type", "Host", "Model", "Uptime"]) {
      expect(screen.getByRole("columnheader", { name: new RegExp(heading) })).toBeInTheDocument();
    }

    const row = screen.getByRole("row", { name: /primary.*lab-host/ });
    expect(row).toHaveAttribute("data-row-id", "lab-host::zeroclaw::primary");
    expect(within(row).getByRole("img", { name: "zeroclaw" })).toHaveAttribute("data-i7n-component", "agent-logo");
    expect(row.querySelector('[data-status="running"]')).toBeInTheDocument();
    expect(within(row).getByLabelText("Linux")).toBeInTheDocument();
    expect(within(row).getAllByText("—")).toHaveLength(2);
    expect(screen.getByText("1 agent")).toBeInTheDocument();
  });

  it("exposes agent navigation as a real named link without making the row tabbable", () => {
    mocks.fleetState.data = fleet;
    render(<AgentTable />);

    const row = screen.getByRole("row", { name: /primary.*lab-host/ });
    expect(row).not.toHaveAttribute("tabindex");
    expect(within(row).getByRole("link", { name: "Open agent primary" })).toHaveAttribute(
      "href",
      "/agents?key=lab-host%3A%3Azeroclaw%3A%3Aprimary",
    );
  });
});
