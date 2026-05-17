import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkillDetail } from "./skill-detail";
import type { SkillDetail as SkillDetailData } from "@/lib/types";

function makeDetail(
  overrides: Partial<SkillDetailData> = {},
): SkillDetailData {
  return {
    ref: "clawrium/tdd",
    registry: "clawrium",
    name: "tdd",
    metadata: {
      name: "tdd",
      description: "TDD discipline.",
      version: "0.1.0",
      license: "MIT",
      author: "clawrium",
      platforms: ["linux", "macos"],
    },
    body: "# Body content\n",
    compatibility: { openclaw: true, hermes: true, zeroclaw: true },
    ...overrides,
  };
}

describe("SkillDetail", () => {
  it("renders the ref and description", () => {
    render(<SkillDetail skill={makeDetail()} />);
    expect(screen.getByText("clawrium/tdd")).toBeInTheDocument();
    expect(screen.getByText("TDD discipline.")).toBeInTheDocument();
  });

  it("renders core metadata fields", () => {
    render(
      <SkillDetail
        skill={makeDetail({
          metadata: {
            name: "tdd",
            description: "TDD discipline.",
            version: "0.1.0",
            license: "MIT",
            author: "ada",
            platforms: ["linux", "macos"],
          },
        })}
      />,
    );
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText("MIT")).toBeInTheDocument();
    expect(screen.getByText("ada")).toBeInTheDocument();
    expect(screen.getByText("linux, macos")).toBeInTheDocument();
  });

  it("renders compatibility badges for every claw", () => {
    render(<SkillDetail skill={makeDetail()} />);
    expect(screen.getByText("openclaw")).toBeInTheDocument();
    expect(screen.getByText("hermes")).toBeInTheDocument();
    expect(screen.getByText("zeroclaw")).toBeInTheDocument();
  });

  it("renders SKILL.md body", () => {
    render(<SkillDetail skill={makeDetail()} />);
    expect(screen.getByText(/Body content/)).toBeInTheDocument();
  });

  it("makes the SKILL.md body keyboard-scrollable", () => {
    render(<SkillDetail skill={makeDetail()} />);
    // WCAG 2.1.1 Level A — scrollable region must be reachable from
    // the keyboard. The <pre> carries tabIndex=0 + an aria-label.
    const pre = screen.getByLabelText("SKILL.md body, scrollable");
    expect(pre.tagName).toBe("PRE");
    expect(pre.getAttribute("tabindex")).toBe("0");
  });

  it("omits optional fields when missing", () => {
    render(
      <SkillDetail
        skill={makeDetail({
          metadata: { name: "tdd", description: "Just the basics." },
        })}
      />,
    );
    expect(screen.queryByText("MIT")).not.toBeInTheDocument();
    expect(screen.queryByText("linux, macos")).not.toBeInTheDocument();
  });

  it("strikethrough-styles claws that are incompatible", () => {
    render(
      <SkillDetail
        skill={makeDetail({
          compatibility: { openclaw: true, hermes: false, zeroclaw: false },
        })}
      />,
    );
    const hermes = screen.getByText("hermes");
    expect(hermes.className).toMatch(/line-through/);
  });

  it("uses comma-separated aria-labels for compatibility badges", () => {
    render(
      <SkillDetail
        skill={makeDetail({
          compatibility: { openclaw: true, hermes: false, zeroclaw: true },
        })}
      />,
    );
    expect(
      screen.getByLabelText("openclaw, compatible"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("hermes, incompatible"),
    ).toBeInTheDocument();
    // No em-dash anywhere — NVDA/JAWS read U+2014 as "em dash".
    const badges = screen.getAllByText(/openclaw|hermes|zeroclaw/);
    for (const badge of badges) {
      const label = badge.getAttribute("aria-label") ?? "";
      expect(label).not.toMatch(/—/);
    }
  });
});
