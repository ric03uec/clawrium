import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TopologyResponse } from "@/lib/types";

const state = vi.hoisted(() => ({
  data: undefined as TopologyResponse | undefined,
  isLoading: false,
}));

vi.mock("@/hooks/use-topology", () => ({
  useTopology: () => state,
}));

import { HostTable } from "./host-table";

const topology: TopologyResponse = {
  control: { label: "Control", description: "clawctl CLI" },
  summary: { total_agents: 2, running: 1, total_hosts: 2 },
  connections: [],
  hosts: [
    {
      hostname: "wolf-i.example",
      alias: "wolf-i",
      user: "xclm",
      addresses: [{ address: "192.0.2.10", is_primary: true, label: "lan" }],
      has_key: true,
      agent_count: 2,
      agents: [],
      os_family: "linux",
      hardware: {
        architecture: "x86_64",
        cores: 16,
        memtotal_mb: 32768,
        gpu: { present: false, vendor: null },
        product_name: null,
        system_vendor: null,
      },
    },
    {
      hostname: "studio.example",
      alias: "Studio Mac",
      user: "admin",
      addresses: [],
      has_key: false,
      agent_count: 0,
      agents: [],
      os_family: "darwin",
      hardware: null,
    },
  ],
};

describe("HostTable", () => {
  it("renders loading and empty states through DataTable", () => {
    state.data = undefined;
    state.isLoading = true;
    const { rerender } = render(<HostTable />);
    expect(screen.getByRole("cell", { name: "Loading hosts..." })).toBeInTheDocument();

    state.isLoading = false;
    rerender(<HostTable />);
    expect(screen.getByRole("cell", { name: "No hosts registered yet" })).toBeInTheDocument();
  });

  it("renders host identity, access, agent count, and hardware columns", () => {
    state.data = topology;
    state.isLoading = false;
    render(<HostTable />);

    for (const heading of ["Name", "Address", "SSH user", "Agents", "Architecture", "SSH access"]) {
      expect(screen.getByRole("columnheader", { name: new RegExp(heading) })).toBeInTheDocument();
    }

    const wolf = screen.getByRole("row", { name: /wolf-i.*192\.0\.2\.10/ });
    expect(wolf).toHaveAttribute("data-row-id", "wolf-i.example");
    expect(within(wolf).getByLabelText("Linux")).toBeInTheDocument();
    expect(within(wolf).getByText("2 agents")).toBeInTheDocument();
    expect(within(wolf).getByText("x86_64")).toBeInTheDocument();
    expect(within(wolf).getByText("Ready")).toHaveAttribute("data-status", "valid");

    const studio = screen.getByRole("row", { name: /Studio Mac.*studio\.example/ });
    expect(within(studio).getByText("Missing key")).toHaveAttribute("data-status", "not_installed");
    expect(within(studio).getByText("—")).toBeInTheDocument();
    expect(screen.getByText("2 hosts")).toBeInTheDocument();
  });
});
