import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TabNav } from "./tab-nav";

describe("TabNav", () => {
  it("uses the shared TabBar while preserving selection and callbacks", () => {
    const onChange = vi.fn();
    render(<TabNav active="overview" onChange={onChange} />);

    expect(screen.getByRole("tablist", { name: "Agent detail tabs" })).toHaveAttribute(
      "data-i7n-name",
      "agent-detail.page.tabs",
    );
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-controls",
      "agent-detail-page-tabs-panel-overview",
    );
    expect(screen.getByRole("tab", { name: "Configuration" })).toHaveAttribute("aria-selected", "false");
    fireEvent.click(screen.getByRole("tab", { name: "Logs" }));
    expect(onChange).toHaveBeenCalledWith("logs");
  });

  it("does not render Chat / Exec / Memory tabs after #1071", () => {
    const onChange = vi.fn();
    render(<TabNav active="overview" onChange={onChange} />);
    expect(screen.queryByRole("tab", { name: "Chat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Exec" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Memory" })).not.toBeInTheDocument();
  });
});
