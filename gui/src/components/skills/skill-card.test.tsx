import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SkillCard } from "./skill-card";
import type { SkillSummary } from "@/lib/types";

function makeSkill(overrides: Partial<SkillSummary> = {}): SkillSummary {
  return {
    ref: "clawrium/tdd",
    registry: "clawrium",
    name: "tdd",
    description: "Test-Driven Development discipline.",
    version: "0.1.0",
    ...overrides,
  };
}

describe("SkillCard", () => {
  it("renders the ref and version", () => {
    render(<SkillCard skill={makeSkill()} onSelect={() => {}} />);
    expect(screen.getByText("clawrium/tdd")).toBeInTheDocument();
    expect(screen.getByText("v0.1.0")).toBeInTheDocument();
  });

  it("renders the description", () => {
    render(<SkillCard skill={makeSkill()} onSelect={() => {}} />);
    expect(
      screen.getByText("Test-Driven Development discipline."),
    ).toBeInTheDocument();
  });

  it("falls back to placeholder when description is null", () => {
    render(
      <SkillCard
        skill={makeSkill({ description: null })}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText("No description available")).toBeInTheDocument();
  });

  it("marks the card when the skill is degraded", () => {
    render(
      <SkillCard
        skill={makeSkill({ description: null, degraded: true })}
        onSelect={() => {}}
      />,
    );
    // Visible warning chip + descriptive fallback text.
    expect(
      screen.getByLabelText("metadata failed to load"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Failed to load skill metadata"),
    ).toBeInTheDocument();
  });

  it("omits version label when missing", () => {
    render(
      <SkillCard skill={makeSkill({ version: null })} onSelect={() => {}} />,
    );
    expect(screen.queryByText(/^v/)).not.toBeInTheDocument();
  });

  it("invokes onSelect when the card is clicked", () => {
    const onSelect = vi.fn();
    render(<SkillCard skill={makeSkill()} onSelect={onSelect} />);
    fireEvent.click(
      screen.getByRole("button", { name: "View skill clawrium/tdd" }),
    );
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("renders a registry badge for each known registry", () => {
    for (const registry of ["clawrium", "openclaw", "hermes", "zeroclaw"] as const) {
      const { unmount } = render(
        <SkillCard
          skill={makeSkill({ registry, ref: `${registry}/x`, name: "x" })}
          onSelect={() => {}}
        />,
      );
      expect(screen.getByText(`${registry}/x`)).toBeInTheDocument();
      unmount();
    }
  });
});
