import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkillDetail } from "./skill-detail";
import type { SkillDetail as SkillDetailData } from "@/lib/types";

const baseDetail: SkillDetailData = {
  ref: "vetted/tdd",
  source: "vetted",
  name: "tdd",
  metadata: {
    name: "tdd",
    description: "Drive a red-green-refactor cycle",
    version: "0.1.0",
    author: "clawrium",
  },
  body: "# TDD\n\nWrite a failing test first.",
  supported_on: { hermes: true, openclaw: false, zeroclaw: false },
};

describe("SkillDetail", () => {
  it("renders ref, metadata, body, and supported_on badges", () => {
    render(<SkillDetail skill={baseDetail} />);
    expect(screen.getByText("vetted/tdd")).toBeInTheDocument();
    expect(
      screen.getByText(/Drive a red-green-refactor cycle/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Write a failing test first/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/hermes, supported/i)).toBeInTheDocument();
    expect(
      screen.getByLabelText(/openclaw, not yet supported/i),
    ).toBeInTheDocument();
  });

  it("hides body section when empty", () => {
    render(<SkillDetail skill={{ ...baseDetail, body: "" }} />);
    expect(screen.queryByText(/SKILL.md/i)).not.toBeInTheDocument();
  });
});
