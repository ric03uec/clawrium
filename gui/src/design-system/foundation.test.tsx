import { createRef, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  AgentLogo,
  AppSidebar,
  Button,
  Card,
  Eyebrow,
  HostCard,
  Input,
  PageHeader,
  StatBlock,
  StatusChip,
  StatusLight,
  TabBar,
} from "./index";

function TabHarness() {
  const [value, setValue] = useState("overview");
  return (
    <>
      <TabBar
        trackingId="test.tabs.keyboard"
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "skills", label: "Skills" },
          { id: "logs", label: "Logs" },
        ]}
        value={value}
        onValueChange={setValue}
      />
      <div
        role="tabpanel"
        id={`test-tabs-keyboard-panel-${value}`}
        aria-labelledby={`test-tabs-keyboard-tab-${value}`}
      >
        {value} content
      </div>
    </>
  );
}

describe("design-system foundation", () => {
  it("preserves public tracking attributes", () => {
    const { container } = render(
      <div>
        <Button trackingId="test.button.save">Save</Button>
        <Card trackingId="test.card.summary">Card</Card>
        <Input trackingId="test.input.name" aria-label="Name" />
        <StatusChip trackingId="test.status.online" status="online" />
        <StatBlock trackingId="test.stat.agents" value="3">Agents</StatBlock>
        <PageHeader trackingId="test.header.hosts" eyebrow="Fleet" title="Hosts" />
        <TabBar
          trackingId="test.tabs.view"
          tabs={[{ id: "list", label: "List" }]}
          value="list"
          onValueChange={() => undefined}
        />
        <HostCard trackingId="test.host.local" name="Local" kind="linux" />
        <AgentLogo trackingId="test.logo.agent" kind="zeroclaw" />
        <Eyebrow trackingId="test.eyebrow.section">Section</Eyebrow>
        <StatusLight trackingId="test.light.health" />
      </div>
    );

    const expected = [
      ["button", "test.button.save"],
      ["card", "test.card.summary"],
      ["input", "test.input.name"],
      ["status-chip", "test.status.online"],
      ["stat-block", "test.stat.agents"],
      ["page-header", "test.header.hosts"],
      ["tab-bar", "test.tabs.view"],
      ["host-card", "test.host.local"],
      ["agent-logo", "test.logo.agent"],
      ["eyebrow", "test.eyebrow.section"],
      ["status-light", "test.light.health"],
    ];

    for (const [component, name] of expected) {
      expect(container.querySelector(`[data-i7n-component="${component}"][data-i7n-name="${name}"]`)).toBeInTheDocument();
    }
  });

  it("owns sidebar navigation, active state, and collapse behavior", async () => {
    const user = userEvent.setup();
    render(
      <AppSidebar
        trackingId="test.sidebar.shell"
        ariaLabel="Test navigation"
        brand={{ label: "Test", subtitle: "Fleet", href: "/", logoSrc: "/logo.png" }}
        groups={[{
          label: "Main",
          items: [
            { label: "Agents", description: "Manage agents", href: "/agents", icon: <span>A</span>, active: true },
          ],
        }]}
        actions={[{ label: "Settings", href: "/settings", icon: <span>S</span> }]}
        collapseIcons={{ expanded: <span>E</span>, collapsed: <span>C</span> }}
        version="1.2.3"
      />,
    );

    const sidebar = screen.getByRole("complementary", { name: "Test navigation" });
    expect(sidebar).toHaveAttribute("data-i7n-component", "app-sidebar");
    expect(screen.getByRole("link", { name: "Agents" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Manage agents")).toBeInTheDocument();
    expect(screen.getByText("v1.2.3")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(sidebar).toHaveAttribute("data-collapsed", "true");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-expanded", "false");
  });

  it("handles Button clicks and native disabled behavior", async () => {
    const user = userEvent.setup();
    const enabledClick = vi.fn();
    const disabledClick = vi.fn();
    render(
      <>
        <Button trackingId="test.button.enabled" onClick={enabledClick}>Enabled</Button>
        <Button trackingId="test.button.disabled" disabled onClick={disabledClick}>Disabled</Button>
      </>
    );

    await user.click(screen.getByRole("button", { name: "Enabled" }));
    await user.click(screen.getByRole("button", { name: "Disabled" }));
    expect(enabledClick).toHaveBeenCalledOnce();
    expect(disabledClick).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Disabled" })).toBeDisabled();
  });

  it("preserves migrated Button danger/ref and Card padding contracts", () => {
    const ref = createRef<HTMLButtonElement>();
    const { container } = render(
      <>
        <Button ref={ref} trackingId="test.button.danger" variant="danger">Delete</Button>
        <Card trackingId="test.card.padding" padding="lg" data-testid="card">Card</Card>
      </>
    );
    expect(ref.current).toBe(screen.getByRole("button", { name: "Delete" }));
    expect(ref.current).toHaveAttribute("data-variant", "danger");
    expect(screen.getByTestId("card")).toHaveAttribute("data-padding", "lg");
    expect(container.querySelector('[data-i7n-name="test.card.padding"]')).toBeInTheDocument();
  });

  it("records Input size on the DOM root", () => {
    render(<Input trackingId="test.input.search" size="sm" aria-label="Search" />);
    expect(screen.getByRole("textbox", { name: "Search" })).toHaveAttribute("data-size", "sm");
  });

  it("exposes tab roles, selection, and callback", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <TabBar
        trackingId="test.tabs.agent"
        tabs={[{ id: "overview", label: "Overview" }, { id: "logs", label: "Logs" }]}
        value="overview"
        onValueChange={onValueChange}
      />
    );

    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: "Logs" }));
    expect(onValueChange).toHaveBeenCalledWith("logs");
  });

  it("uses roving focus, selects with standard arrow keys, and links tabs to panels", async () => {
    const user = userEvent.setup();
    render(<TabHarness />);

    const overview = screen.getByRole("tab", { name: "Overview" });
    const skills = screen.getByRole("tab", { name: "Skills" });
    const logs = screen.getByRole("tab", { name: "Logs" });
    expect(overview).toHaveAttribute("tabindex", "0");
    expect(skills).toHaveAttribute("tabindex", "-1");
    expect(overview).toHaveAttribute("aria-controls", "test-tabs-keyboard-panel-overview");

    overview.focus();
    await user.keyboard("{ArrowRight}");
    expect(skills).toHaveFocus();
    expect(skills).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", skills.id);

    await user.keyboard("{End}");
    expect(logs).toHaveFocus();
    await user.keyboard("{Home}");
    expect(overview).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(logs).toHaveFocus();
  });

  it("renders StatusChip status and an optional label", () => {
    const { rerender } = render(<StatusChip trackingId="test.status.active" status="active" />);
    expect(screen.getByText("active")).toHaveAttribute("data-status", "active");
    rerender(<StatusChip trackingId="test.status.active" status="active" label="Ready" />);
    expect(screen.getByText("Ready")).toHaveAttribute("data-status", "active");
  });

  it.each([
    ["claude", "/agents/claude.svg"],
    ["codex", "/agents/openai.svg"],
    ["ethos", "/agents/ethos.svg"],
    ["hermes", "/agents/hermes.svg"],
    ["openclaw", "/agents/openclaw.svg"],
    ["pi", "/agents/pi.svg"],
    ["zeroclaw", "/agents/zeroclaw.svg"],
  ])("maps the supported %s agent type to its official asset", (kind, src) => {
    render(<AgentLogo trackingId={`test.logo.${kind}`} kind={kind} size={20} />);
    const logo = screen.getByRole("img", { name: kind });
    expect(logo).toHaveAttribute("src", src);
    expect(logo).toHaveAttribute("data-kind", kind);
  });

  it("uses a deterministic AgentLogo glyph fallback", () => {
    render(<AgentLogo trackingId="test.logo.unknown" kind="unknown" size={20} />);
    const fallback = screen.getByLabelText("unknown");
    expect(fallback).toHaveTextContent("U");
    expect(fallback).toHaveAttribute("data-kind", "unknown");
    expect(fallback).toHaveStyle({ width: "20px", height: "20px" });
  });

  it("renders HostCard empty and overflow states", () => {
    const { rerender } = render(
      <HostCard trackingId="test.host.empty" name="Empty host" kind="linux" emptyMessage="Nothing installed" />
    );
    expect(screen.getByText("Nothing installed")).toBeInTheDocument();

    rerender(
      <HostCard
        trackingId="test.host.full"
        name="Full host"
        kind="linux"
        maxVisibleAgents={2}
        moreHref="/hosts/full"
        agents={[
          { id: "one", name: "One", kind: "zeroclaw", light: "green" },
          { id: "two", name: "Two", kind: "hermes", light: "yellow" },
          { id: "three", name: "Three", kind: "openclaw", light: "gray" },
        ]}
      />
    );
    expect(screen.getByText("One")).toBeInTheDocument();
    expect(screen.getByText("Two")).toBeInTheDocument();
    expect(screen.queryByText("Three")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+1 more" })).toHaveAttribute("href", "/hosts/full");
  });
});
