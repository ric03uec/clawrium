import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SkillCard } from "./skill-card";
import type { SkillSummary } from "@/lib/types";

const baseSkill: SkillSummary = {
  ref: "vetted/tdd",
  source: "vetted",
  name: "tdd",
  description: "Drive a red-green-refactor cycle",
  version: "0.1.0",
  supported_on: { hermes: true, openclaw: false, zeroclaw: false },
};

describe("SkillCard", () => {
  it("renders the ref, version, description and source badge", () => {
    render(<SkillCard skill={baseSkill} onSelect={() => {}} />);
    expect(screen.getByText("vetted/tdd")).toBeInTheDocument();
    expect(screen.getByText("v0.1.0")).toBeInTheDocument();
    expect(
      screen.getByText(/Drive a red-green-refactor cycle/i),
    ).toBeInTheDocument();
    expect(screen.getByText("vetted")).toBeInTheDocument();
  });

  it("renders supported_on summary line", () => {
    render(<SkillCard skill={baseSkill} onSelect={() => {}} />);
    expect(screen.getByText(/Supported on: hermes/i)).toBeInTheDocument();
  });

  it("calls onSelect when the card is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<SkillCard skill={baseSkill} onSelect={onSelect} />);
    await user.click(screen.getByRole("button", { name: /view skill/i }));
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("shows degraded marker when metadata failed to load", () => {
    const degraded: SkillSummary = {
      ...baseSkill,
      description: null,
      degraded: true,
    };
    render(<SkillCard skill={degraded} onSelect={() => {}} />);
    expect(
      screen.getByLabelText(/metadata failed to load/i),
    ).toBeInTheDocument();
  });
});
