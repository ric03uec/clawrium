import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentDetail, AgentDetailHealth, AgentStatus } from "@/lib/types";

const webUIState = { data: undefined, isLoading: false, isError: false };
const noopMutation = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };

vi.mock("@/hooks", () => ({
  PAIRING_AGENT_TYPES: new Set(["zeroclaw"]),
  TOKEN_REVEAL_AGENT_TYPES: new Set(["openclaw"]),
  useAgentActions: () => ({
    start: noopMutation,
    stop: noopMutation,
    restart: noopMutation,
  }),
  useAgentConnectionToken: () => ({ ...noopMutation, data: undefined, isError: false, error: null }),
  useAgentPairingCode: () => ({ ...noopMutation, data: undefined, isError: false, error: null }),
  useAgentWebUI: () => webUIState,
}));

import { AgentHeader, lifecycleDisabledReason } from "./agent-header";

function makeAgent(overrides: Partial<AgentDetail> = {}): AgentDetail {
  return {
    agent_key: "demo",
    agent_name: "demo",
    agent_type: "hermes",
    host: "192.168.1.100",
    host_alias: "box",
    host_os_family: "linux",
    status: "checking",
    model: "-",
    uptime: "1m",
    gateway_url: null,
    provider: "",
    provider_type: "",
    addresses: [],
    version: "2026.4.2",
    device_id: "",
    onboarding_step: "ready",
    gateway_port: null,
    ...overrides,
  } as AgentDetail;
}

function makeHealth(
  overrides: Partial<AgentDetailHealth> = {},
): AgentDetailHealth {
  return {
    agent_key: "demo",
    status: "running",
    process_running: true,
    health_error: null,
    cpu_count: 4,
    memory_total_mb: 8192,
    missing_secrets: null,
    onboarding_step: "ready",
    latest_supported_version: null,
    ...overrides,
  };
}

function lifecycleButtons() {
  return {
    start: screen.getByTestId("action-start"),
    restart: screen.getByTestId("action-restart"),
    stop: screen.getByTestId("action-stop"),
  };
}

function isAriaDisabled(el: HTMLElement) {
  return el.getAttribute("aria-disabled") === "true";
}

describe("AgentHeader — chrome", () => {
  it("renders agent identity even when health is undefined", () => {
    render(<AgentHeader agent={makeAgent()} health={undefined} />);
    expect(screen.getByText("demo")).toBeTruthy();
    expect(screen.getByText(/hermes v2026\.4\.2/)).toBeTruthy();
  });
});

describe("lifecycleDisabledReason — pure mapping", () => {
  it.each([
    // action=start: only "stopped" is available
    ["stopped", "start", ""],
    ["running", "start", "Agent is not stopped"],
    ["checking", "start", "Waiting for status…"],
    ["install_missing", "start", "On-host install missing — reinstall required"],
    ["degraded", "start", "Agent is not stopped"],
    // action=restart / stop: only "running" is available
    ["running", "restart", ""],
    ["running", "stop", ""],
    ["stopped", "restart", "Agent is not running"],
    ["stopped", "stop", "Agent is not running"],
    ["checking", "restart", "Waiting for status…"],
    ["install_missing", "restart", "On-host install missing — reinstall required"],
    ["install_missing", "stop", "On-host install missing — reinstall required"],
    ["unknown", "stop", "Agent is not running"],
  ] as const)(
    "%s → %s = %j",
    (status, action, expected) => {
      expect(
        lifecycleDisabledReason(status as AgentStatus, action as "start" | "restart" | "stop"),
      ).toBe(expected);
    },
  );
});

describe("AgentHeader — stable lifecycle action bar (#870)", () => {
  it.each([
    ["checking (health undefined)", undefined],
    ["stopped", makeHealth({ status: "stopped" })],
    ["running", makeHealth({ status: "running" })],
    ["install_missing", makeHealth({ status: "install_missing" })],
    ["degraded", makeHealth({ status: "degraded" })],
  ] as const)("always renders Start, Restart, Stop when %s", (_label, health) => {
    render(<AgentHeader agent={makeAgent()} health={health} />);
    const { start, restart, stop } = lifecycleButtons();
    expect(start).toBeTruthy();
    expect(restart).toBeTruthy();
    expect(stop).toBeTruthy();
  });

  it("renders lifecycle buttons in stable [Start, Restart, Stop] order", () => {
    for (const health of [
      undefined,
      makeHealth({ status: "stopped" }),
      makeHealth({ status: "running" }),
      makeHealth({ status: "install_missing" }),
    ] as const) {
      const { unmount } = render(
        <AgentHeader agent={makeAgent()} health={health} />,
      );
      const buttons = [
        screen.getByTestId("action-start"),
        screen.getByTestId("action-restart"),
        screen.getByTestId("action-stop"),
      ];
      // Confirm DOM order matches array order.
      for (let i = 0; i < buttons.length - 1; i++) {
        expect(
          buttons[i].compareDocumentPosition(buttons[i + 1]) &
            Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
      }
      unmount();
    }
  });

  it("enables Start and aria-disables Restart/Stop when stopped", () => {
    render(
      <AgentHeader
        agent={makeAgent()}
        health={makeHealth({ status: "stopped" })}
      />,
    );
    const { start, restart, stop } = lifecycleButtons();
    expect(isAriaDisabled(start)).toBe(false);
    expect(isAriaDisabled(restart)).toBe(true);
    expect(isAriaDisabled(stop)).toBe(true);
    expect(restart.getAttribute("title")).toMatch(/not running/i);
    expect(stop.getAttribute("title")).toMatch(/not running/i);
  });

  it("enables Restart/Stop and aria-disables Start when running", () => {
    render(<AgentHeader agent={makeAgent()} health={makeHealth()} />);
    const { start, restart, stop } = lifecycleButtons();
    expect(isAriaDisabled(start)).toBe(true);
    expect(isAriaDisabled(restart)).toBe(false);
    expect(isAriaDisabled(stop)).toBe(false);
    expect(start.getAttribute("title")).toMatch(/not stopped/i);
  });

  it("aria-disables all lifecycle buttons while health probe is in flight", () => {
    render(<AgentHeader agent={makeAgent()} health={undefined} />);
    const { start, restart, stop } = lifecycleButtons();
    expect(isAriaDisabled(start)).toBe(true);
    expect(isAriaDisabled(restart)).toBe(true);
    expect(isAriaDisabled(stop)).toBe(true);
    expect(start.getAttribute("title")).toMatch(/waiting for status/i);
  });

  it("aria-disables all lifecycle buttons and shows reinstall hint when install_missing", () => {
    render(
      <AgentHeader
        agent={makeAgent()}
        health={makeHealth({ status: "install_missing" })}
      />,
    );
    const { start, restart, stop } = lifecycleButtons();
    expect(isAriaDisabled(start)).toBe(true);
    expect(isAriaDisabled(restart)).toBe(true);
    expect(isAriaDisabled(stop)).toBe(true);
    expect(start.getAttribute("title")).toMatch(/install missing/i);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText(/On-host install missing/i)).toBeTruthy();
  });

  it("keeps aria-disabled lifecycle buttons in the tab order (native disabled is not used)", () => {
    // Guards against regression to native `disabled`, which drops the
    // button from the tab order and hides it from AT users trying to
    // discover the reason.
    render(<AgentHeader agent={makeAgent()} health={undefined} />);
    const { start, restart, stop } = lifecycleButtons();
    for (const btn of [start, restart, stop]) {
      expect(btn.hasAttribute("disabled")).toBe(false);
      expect(isAriaDisabled(btn)).toBe(true);
    }
  });

  it("does not fire mutations when clicking an aria-disabled lifecycle button", () => {
    // Guarded onClick — aria-disabled alone does NOT block clicks; the
    // handler must early-return. Otherwise a keyboard Enter/Space on a
    // focused aria-disabled button would still mutate.
    const spy = vi.spyOn(noopMutation, "mutate");
    spy.mockClear();
    render(<AgentHeader agent={makeAgent()} health={undefined} />);
    const { start, restart, stop } = lifecycleButtons();
    start.click();
    restart.click();
    stop.click();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("references the reason via aria-describedby when disabled", () => {
    render(
      <AgentHeader
        agent={makeAgent()}
        health={makeHealth({ status: "stopped" })}
      />,
    );
    const { restart } = lifecycleButtons();
    const describedBy = restart.getAttribute("aria-describedby");
    // Id comes from useId() + suffix — shape rather than exact match.
    expect(describedBy).toMatch(/-restart-reason$/);
    const reason = document.getElementById(describedBy!);
    expect(reason?.textContent).toMatch(/not running/i);
  });

  it("gives each instance unique reason ids so multiple headers can co-render", () => {
    // Guards against the module-scope-constant regression: two headers
    // on one page (fleet/list/comparison view) must not collide on
    // aria-describedby target ids. useId() gives per-instance suffixes.
    const { container } = render(
      <>
        <AgentHeader
          agent={makeAgent({ agent_key: "a", agent_name: "a" })}
          health={makeHealth({ status: "stopped" })}
        />
        <AgentHeader
          agent={makeAgent({ agent_key: "b", agent_name: "b" })}
          health={makeHealth({ status: "stopped" })}
        />
      </>,
    );
    const reasonSpans = container.querySelectorAll(
      "[id$='-restart-reason']",
    );
    const ids = Array.from(reasonSpans).map((el) => el.id);
    expect(ids.length).toBe(2);
    expect(new Set(ids).size).toBe(2);
  });
});
