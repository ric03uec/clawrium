import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { AgentSkills } from "@/lib/types";

// Mocked hook state — each test resets the slots in beforeEach.
const agentSkillsState: {
  data: AgentSkills | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
} = { data: undefined, isLoading: false, error: null, refetch: vi.fn() };

const installMutation = {
  mutateAsync: vi.fn(),
  isPending: false,
};
const removeMutation = {
  mutateAsync: vi.fn(),
  isPending: false,
};

vi.mock("@/hooks", () => ({
  useAgentSkills: () => agentSkillsState,
  useInstallAgentSkill: () => installMutation,
  useRemoveAgentSkill: () => removeMutation,
}));

vi.mock("@/components/ui/modal", () => ({
  Modal: ({
    open,
    title,
    children,
    footer,
  }: {
    open: boolean;
    title: string;
    children: React.ReactNode;
    footer?: React.ReactNode;
  }) =>
    open ? (
      <div data-testid="modal">
        <p>{title}</p>
        {children}
        {footer}
      </div>
    ) : null,
}));

import { SkillsTab } from "./skills-tab";

function makeAgentSkills(overrides: Partial<AgentSkills> = {}): AgentSkills {
  return {
    agent_name: "tdd-hermes",
    agent_type: "hermes",
    installed: [],
    available: [
      {
        ref: "clawrium/tdd",
        registry: "clawrium",
        name: "tdd",
        description: "TDD discipline.",
        version: "0.1.0",
      },
    ],
    ...overrides,
  };
}

describe("SkillsTab", () => {
  beforeEach(() => {
    agentSkillsState.data = undefined;
    agentSkillsState.isLoading = false;
    agentSkillsState.error = null;
    agentSkillsState.refetch = vi.fn();
    installMutation.mutateAsync = vi.fn().mockResolvedValue({});
    installMutation.isPending = false;
    removeMutation.mutateAsync = vi.fn().mockResolvedValue({});
    removeMutation.isPending = false;
  });

  it("renders the live region with role=status and aria-busy=true while loading", () => {
    // ATX-3 W1/W2: the live region lives at the SkillsTab root (not
    // inside the skeleton) so it can announce *both* the load start
    // and the transition to loaded. Assert role=status + aria-busy
    // are wired and the announcement text matches the load state.
    agentSkillsState.isLoading = true;
    render(<SkillsTab agentKey="tdd-hermes" />);
    const live = screen.getByRole("status", { name: /Skills tab status/ });
    expect(live).toHaveAttribute("aria-busy", "true");
    expect(live).toHaveTextContent("Loading skills…");
    expect(screen.getByTestId("skills-loading")).toBeInTheDocument();
  });

  it("renders an error state with a retry control", () => {
    agentSkillsState.error = new Error("boom");
    render(<SkillsTab agentKey="tdd-hermes" />);
    expect(screen.getByText(/Failed to load skills/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    expect(agentSkillsState.refetch).toHaveBeenCalled();
  });

  it("shows the empty-state hint when nothing is installed", () => {
    agentSkillsState.data = makeAgentSkills();
    render(<SkillsTab agentKey="tdd-hermes" />);
    expect(screen.getByText(/No skills installed yet/i)).toBeInTheDocument();
  });

  it("renders installed skills with Remove buttons", () => {
    agentSkillsState.data = makeAgentSkills({
      installed: [
        {
          ref: "clawrium/tdd",
          registry: "clawrium",
          name: "tdd",
          description: "TDD discipline.",
          version: "0.1.0",
        },
      ],
    });
    render(<SkillsTab agentKey="tdd-hermes" />);
    expect(screen.getByText("clawrium/tdd")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Remove clawrium\/tdd/ }),
    ).toBeInTheDocument();
  });

  it("opens the install picker filtered to compatible skills", () => {
    agentSkillsState.data = makeAgentSkills();
    render(<SkillsTab agentKey="tdd-hermes" />);
    fireEvent.click(screen.getByRole("button", { name: /Install skill/ }));
    const modal = screen.getByTestId("modal");
    expect(modal).toBeInTheDocument();
    // The picker shows the available skill that isn't yet installed.
    expect(modal.textContent).toContain("clawrium/tdd");
  });

  it("hides already-installed skills from the picker", () => {
    agentSkillsState.data = makeAgentSkills({
      installed: [
        {
          ref: "clawrium/tdd",
          registry: "clawrium",
          name: "tdd",
          description: "TDD discipline.",
          version: "0.1.0",
        },
      ],
    });
    render(<SkillsTab agentKey="tdd-hermes" />);
    // The Install button disables when nothing is available beyond installed.
    expect(
      screen.getByRole("button", { name: /Install skill/ }),
    ).toBeDisabled();
  });

  it("calls install mutation with parsed registry+name", async () => {
    agentSkillsState.data = makeAgentSkills();
    render(<SkillsTab agentKey="tdd-hermes" />);
    fireEvent.click(screen.getByRole("button", { name: /Install skill/ }));
    // Per-row picker button is labeled "Install <ref>" (ATX-1 W7).
    fireEvent.click(
      screen.getByRole("button", { name: /Install clawrium\/tdd/ }),
    );
    await waitFor(() =>
      expect(installMutation.mutateAsync).toHaveBeenCalledWith({
        agentKey: "tdd-hermes",
        registry: "clawrium",
        name: "tdd",
      }),
    );
  });

  it("calls remove mutation only after the confirm step", async () => {
    // ATX-1 B2: destructive Remove is a two-step. First click arms the
    // confirm/cancel pair; the mutation only fires on the Confirm click.
    agentSkillsState.data = makeAgentSkills({
      installed: [
        {
          ref: "clawrium/tdd",
          registry: "clawrium",
          name: "tdd",
          description: "TDD discipline.",
          version: "0.1.0",
        },
      ],
    });
    render(<SkillsTab agentKey="tdd-hermes" />);

    // Step 1: clicking "Remove" must NOT call the mutation.
    fireEvent.click(
      screen.getByRole("button", { name: /^Remove clawrium\/tdd$/ }),
    );
    expect(removeMutation.mutateAsync).not.toHaveBeenCalled();

    // The confirm/cancel pair is now rendered, labelled with the ref.
    expect(
      screen.getByRole("group", {
        name: /Confirm removal of clawrium\/tdd/,
      }),
    ).toBeInTheDocument();

    // Step 2: confirm.
    fireEvent.click(
      screen.getByRole("button", { name: /Confirm remove clawrium\/tdd/ }),
    );
    await waitFor(() =>
      expect(removeMutation.mutateAsync).toHaveBeenCalledWith({
        agentKey: "tdd-hermes",
        registry: "clawrium",
        name: "tdd",
      }),
    );
  });

  it("cancels the remove confirmation without firing the mutation", () => {
    agentSkillsState.data = makeAgentSkills({
      installed: [
        {
          ref: "clawrium/tdd",
          registry: "clawrium",
          name: "tdd",
          description: "TDD discipline.",
          version: "0.1.0",
        },
      ],
    });
    render(<SkillsTab agentKey="tdd-hermes" />);
    fireEvent.click(
      screen.getByRole("button", { name: /^Remove clawrium\/tdd$/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Cancel remove clawrium\/tdd/ }),
    );
    expect(removeMutation.mutateAsync).not.toHaveBeenCalled();
    // Confirmation UI is gone; the original Remove button is back.
    expect(
      screen.getByRole("button", { name: /^Remove clawrium\/tdd$/ }),
    ).toBeInTheDocument();
  });

  it("surfaces install errors inline", async () => {
    agentSkillsState.data = makeAgentSkills();
    installMutation.mutateAsync = vi
      .fn()
      .mockRejectedValue(new Error("host unreachable"));
    render(<SkillsTab agentKey="tdd-hermes" />);
    fireEvent.click(screen.getByRole("button", { name: /Install skill/ }));
    fireEvent.click(
      screen.getAllByRole("button", { name: /Install clawrium\/tdd/ })[0],
    );
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/host unreachable/);
    });
  });

  it("surfaces remove errors inline and resets confirming state", async () => {
    // ATX-1 W9 + ATX-2 W9: handleRemove has the same catch path as
    // handleInstall, AND after a failed mutation the row must drop
    // back to the un-armed state — otherwise the user is stuck staring
    // at Confirm/Cancel with no way to retry the Remove from the
    // resting state.
    agentSkillsState.data = makeAgentSkills({
      installed: [
        {
          ref: "clawrium/tdd",
          registry: "clawrium",
          name: "tdd",
          description: "TDD discipline.",
          version: "0.1.0",
        },
      ],
    });
    removeMutation.mutateAsync = vi
      .fn()
      .mockRejectedValue(new Error("ansible timeout"));
    render(<SkillsTab agentKey="tdd-hermes" />);
    fireEvent.click(
      screen.getByRole("button", { name: /^Remove clawrium\/tdd$/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Confirm remove clawrium\/tdd/ }),
    );
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/ansible timeout/);
    });
    // The mutation handler clears `confirming` synchronously when the
    // Confirm button fires, so the resting "Remove" button is back.
    expect(
      screen.getByRole("button", { name: /^Remove clawrium\/tdd$/ }),
    ).toBeInTheDocument();
  });

  it("dismisses the confirm group on Escape from the Confirm button", () => {
    // ATX-2 B2b: Escape on the inline confirm group must cancel.
    // ATX-3 W4: fire Escape on the *focused* Confirm button so the
    // event-bubble path is exercised, not a synthetic group keydown
    // that would bypass any accidentally-added child stopPropagation.
    agentSkillsState.data = makeAgentSkills({
      installed: [
        {
          ref: "clawrium/tdd",
          registry: "clawrium",
          name: "tdd",
          description: "TDD discipline.",
          version: "0.1.0",
        },
      ],
    });
    render(<SkillsTab agentKey="tdd-hermes" />);
    fireEvent.click(
      screen.getByRole("button", { name: /^Remove clawrium\/tdd$/ }),
    );
    const confirmBtn = screen.getByRole("button", {
      name: /Confirm remove clawrium\/tdd/,
    });
    fireEvent.keyDown(confirmBtn, { key: "Escape" });
    expect(
      screen.queryByRole("group", {
        name: /Confirm removal of clawrium\/tdd/,
      }),
    ).not.toBeInTheDocument();
  });

  it("focuses the Confirm button on Remove→confirming transition", async () => {
    // ATX-2 B2a: focus must move so keyboard / SR users notice the
    // state change. S1: waitFor so a future requestAnimationFrame
    // delay doesn't silently make this assertion vacuous.
    agentSkillsState.data = makeAgentSkills({
      installed: [
        {
          ref: "clawrium/tdd",
          registry: "clawrium",
          name: "tdd",
          description: "TDD discipline.",
          version: "0.1.0",
        },
      ],
    });
    render(<SkillsTab agentKey="tdd-hermes" />);
    fireEvent.click(
      screen.getByRole("button", { name: /^Remove clawrium\/tdd$/ }),
    );
    const confirmBtn = screen.getByRole("button", {
      name: /Confirm remove clawrium\/tdd/,
    });
    await waitFor(() => expect(confirmBtn).toHaveFocus());
  });

  it("dismisses the confirm group when a concurrent mutation disables the row", () => {
    // ATX-3 W3: assert the disabled→confirming-cleanup effect, which
    // is the only thing standing between "two mutations in flight"
    // and "user sees a stuck disabled Confirm button they cannot
    // escape from".
    agentSkillsState.data = makeAgentSkills({
      installed: [
        {
          ref: "clawrium/tdd",
          registry: "clawrium",
          name: "tdd",
          description: "TDD discipline.",
          version: "0.1.0",
        },
      ],
    });
    const { rerender } = render(<SkillsTab agentKey="tdd-hermes" />);
    fireEvent.click(
      screen.getByRole("button", { name: /^Remove clawrium\/tdd$/ }),
    );
    expect(
      screen.getByRole("group", { name: /Confirm removal of clawrium\/tdd/ }),
    ).toBeInTheDocument();

    // Concurrent install fires — the row disables. The effect must
    // collapse the confirm group back to the resting Remove button.
    installMutation.isPending = true;
    rerender(<SkillsTab agentKey="tdd-hermes" />);
    expect(
      screen.queryByRole("group", {
        name: /Confirm removal of clawrium\/tdd/,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Remove clawrium\/tdd$/ }),
    ).toBeDisabled();
  });

  it("closes the install picker after a successful install", async () => {
    // ATX-1 W9: post-install modal-close path was previously uncovered.
    agentSkillsState.data = makeAgentSkills();
    render(<SkillsTab agentKey="tdd-hermes" />);
    fireEvent.click(screen.getByRole("button", { name: /Install skill/ }));
    expect(screen.getByTestId("modal")).toBeInTheDocument();
    fireEvent.click(
      screen.getAllByRole("button", { name: /Install clawrium\/tdd/ })[0],
    );
    await waitFor(() => {
      expect(screen.queryByTestId("modal")).not.toBeInTheDocument();
    });
  });
});
