import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type {
  SkillsCatalog,
  SkillDetail as SkillDetailData,
} from "@/lib/types";

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
  useFleet: () => ({
    data: {
      agents: [],
      summary: { total: 0, running: 0, provisioning: 0, hosts: 0 },
    },
  }),
  useInstallAgentSkill: () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  }),
  useCreateSkill: () => ({
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  }),
  useDeleteSkill: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}));

// jsdom doesn't support HTMLDialogElement.showModal / close
beforeEach(() => {
  if (
    typeof window !== "undefined" &&
    !HTMLDialogElement.prototype.showModal
  ) {
    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute("open", "");
    };
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute("open");
    };
  }
});

import SkillsPage from "./page";

const SUPPORT = { hermes: true, openclaw: false, zeroclaw: false };

describe("SkillsPage", () => {
  beforeEach(() => {
    skillsState.data = undefined;
    skillsState.isLoading = false;
    skillsState.error = null;
  });

  it("renders the Create button and page header", () => {
    skillsState.data = {
      sources: ["vetted", "local"],
      supported_on: SUPPORT,
      skills: [],
    };
    render(<SkillsPage />);
    expect(screen.getByText(/Skills/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /\+ Create Skill/i }),
    ).toBeInTheDocument();
  });

  it("renders flat list of skills from catalog", () => {
    skillsState.data = {
      sources: ["vetted", "local"],
      supported_on: SUPPORT,
      skills: [
        {
          ref: "vetted/tdd",
          source: "vetted",
          name: "tdd",
          description: "Drive red-green-refactor",
          version: "0.1.0",
          supported_on: SUPPORT,
        },
        {
          ref: "local/my-skill",
          source: "local",
          name: "my-skill",
          description: "User-authored",
          version: null,
          supported_on: SUPPORT,
        },
      ],
    };
    render(<SkillsPage />);
    expect(screen.getByText("vetted/tdd")).toBeInTheDocument();
    expect(screen.getByText("local/my-skill")).toBeInTheDocument();
  });

  it("shows empty state when catalog is empty", () => {
    skillsState.data = {
      sources: ["vetted", "local"],
      supported_on: SUPPORT,
      skills: [],
    };
    render(<SkillsPage />);
    expect(screen.getByText(/No skills in the catalog/i)).toBeInTheDocument();
  });
});
