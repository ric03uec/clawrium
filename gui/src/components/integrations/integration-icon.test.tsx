import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IntegrationIcon } from "./integration-icon";

describe("IntegrationIcon", () => {
  it.each([
    ["github", "/integration-icons/github.svg"],
    ["gitlab", "/integration-icons/gitlab.svg"],
    ["atlassian", "/integration-icons/atlassian.svg"],
    ["linear", "/integration-icons/linear.svg"],
    ["notion", "/integration-icons/notion.svg"],
    ["brave", "/integration-icons/brave.svg"],
    ["git", "/integration-icons/git.svg"],
  ])("renders the official icon for %s", (type, expectedSrc) => {
    render(<IntegrationIcon type={type} />);
    const img = screen.getByRole("img", { name: `${type} logo` });
    expect(img).toHaveAttribute("src", expectedSrc);
  });

  it("falls back to a label when the type is unknown", () => {
    render(<IntegrationIcon type="custom" />);
    expect(screen.getByLabelText("custom icon")).toHaveTextContent("cu");
  });
});
