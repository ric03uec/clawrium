import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricCard } from "./metric-card";

describe("MetricCard", () => {
  it("renders through StatBlock with labels and optional source", () => {
    const { container } = render(
      <MetricCard
        trackingId="dashboard.metrics.running"
        label="Running"
        value={3}
        sublabel="of 5"
      />,
    );
    const stat = container.querySelector('[data-i7n-name="dashboard.metrics.running"]');
    expect(stat).toHaveAttribute("data-i7n-component", "stat-block");
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText("of 5")).toBeInTheDocument();
  });
});
