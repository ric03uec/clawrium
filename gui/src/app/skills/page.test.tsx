import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type {
  SkillsCatalog,
  SkillDetail as SkillDetailData,
} from "@/lib/types";

// Mock the hooks so we don't need to spin up a QueryClient or stub
// fetch. The page is thin enough that asserting the rendered shape
// against the mocked data is the right unit-test boundary.
const skillsState: {
  data: SkillsCatalog | undefined;
  isLoading: boolean;
  error: unknown;
} = { data: undefined, isLoading: false, error: null };
const skillState: {
  data: SkillDetailData | undefined;
  isLoading: boolean;
  error: unknown;
} = { data: undefined, isLoading: false, error: null };

vi.mock("@/hooks", () => ({
  useSkills: () => skillsState,
  useSkill: () => skillState,
}));

// The Modal component uses HTMLDialogElement#showModal which jsdom only
// supports partially. Substitute a simple visible container.
vi.mock("@/components/ui/modal", () => ({
  Modal: ({
    open,
    title,
    children,
  }: {
    open: boolean;
    title: string;
    children: React.ReactNode;
  }) =>
    open ? (
      <div data-testid="modal">
        <p>{title}</p>
        {children}
      </div>
    ) : null,
}));

import SkillsPage from "./page";

function makeCatalog(): SkillsCatalog {
  return {
    registries: ["clawrium", "openclaw", "hermes", "zeroclaw"],
    skills: {
      clawrium: [
        {
          ref: "clawrium/tdd",
          registry: "clawrium",
          name: "tdd",
          description: "TDD discipline.",
          version: "0.1.0",
        },
      ],
      openclaw: [],
      hermes: [],
      zeroclaw: [],
    },
  };
}

describe("SkillsPage", () => {
  beforeEach(() => {
    skillsState.data = undefined;
    skillsState.isLoading = false;
    skillsState.error = null;
    skillState.data = undefined;
    skillState.isLoading = false;
    skillState.error = null;
  });

  it("renders loading state", () => {
    skillsState.isLoading = true;
    render(<SkillsPage />);
    expect(screen.getByText(/Loading skills catalog/i)).toBeInTheDocument();
  });

  it("renders an error message when the fetch fails", () => {
    skillsState.error = new Error("boom");
    render(<SkillsPage />);
    expect(screen.getByText(/Failed to load skills catalog/)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });

  it("renders a tab per registry with counts", () => {
    skillsState.data = makeCatalog();
    render(<SkillsPage />);
    const nav = screen.getByRole("navigation", { name: "Skill registries" });
    const tabs = nav.querySelectorAll("button");
    expect(tabs).toHaveLength(4);
    // The clawrium tab starts active and shows count 1.
    const clawriumTab = screen.getByRole("button", {
      name: /Clawrium.*1 skill/i,
    });
    expect(clawriumTab).toHaveAttribute("aria-current", "true");
    expect(clawriumTab.textContent).toMatch(/1/);
  });

  it("pluralizes the screen-reader count correctly", () => {
    skillsState.data = makeCatalog();
    render(<SkillsPage />);
    // Hermes is empty (count 0) — must read "0 skills", not "0 skill".
    const hermesTab = screen.getByRole("button", {
      name: /Hermes.*0 skills/i,
    });
    expect(hermesTab).toBeInTheDocument();
  });

  it("renders the SkillCard for the active registry", () => {
    skillsState.data = makeCatalog();
    render(<SkillsPage />);
    expect(screen.getByText("clawrium/tdd")).toBeInTheDocument();
  });

  it("renders the empty-state hint when a tab has no skills", () => {
    skillsState.data = makeCatalog();
    render(<SkillsPage />);
    fireEvent.click(screen.getByRole("button", { name: /Hermes.*0 skills/i }));
    expect(
      screen.getByText((_, node) => node?.textContent === "skills/hermes/<name>/"),
    ).toBeInTheDocument();
  });

  it("opens the detail modal when a skill is clicked", () => {
    skillsState.data = makeCatalog();
    skillState.data = {
      ref: "clawrium/tdd",
      registry: "clawrium",
      name: "tdd",
      metadata: { name: "tdd", description: "TDD discipline." },
      body: "# body",
      compatibility: { openclaw: true, hermes: true, zeroclaw: true },
    };
    render(<SkillsPage />);
    fireEvent.click(
      screen.getByRole("button", { name: "View skill clawrium/tdd" }),
    );
    const modal = screen.getByTestId("modal");
    expect(modal).toBeInTheDocument();
    // Detail panel is rendered inside the modal. Scope the description
    // lookup to the modal so it doesn't collide with the card outside.
    expect(modal.textContent).toContain("TDD discipline.");
  });
});
