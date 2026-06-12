import { render, screen, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { ComingSoonModal } from "./coming-soon-modal";

// jsdom does not implement HTMLDialogElement.showModal / close. Mirrors
// the shim in modal.test.tsx; the Modal wrapped by ComingSoonModal
// crashes without it.
beforeEach(() => {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function showModal(
      this: HTMLDialogElement,
    ) {
      this.setAttribute("open", "");
    };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function close(
      this: HTMLDialogElement,
    ) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    };
  }
});

const DEFAULT_PROPS = {
  open: true,
  onClose: vi.fn(),
  featureName: "MCPs",
  body: "Not yet available.",
  upvoteUrl: "https://github.com/ric03uec/clawrium/issues/698",
};

function renderModal(overrides: Partial<typeof DEFAULT_PROPS> = {}) {
  return render(<ComingSoonModal {...DEFAULT_PROPS} {...overrides} />);
}

describe("ComingSoonModal", () => {
  it("renders the per-feature heading", () => {
    renderModal();
    expect(
      screen.getByRole("heading", { name: /MCPs — coming soon/i }),
    ).toBeInTheDocument();
  });

  it("renders the body copy verbatim", () => {
    renderModal({ body: "Specific roadmap copy goes here." });
    expect(
      screen.getByText("Specific roadmap copy goes here."),
    ).toBeInTheDocument();
  });

  it("returns null when open=false", () => {
    const { container } = renderModal({ open: false });
    expect(container).toBeEmptyDOMElement();
  });

  // W4: lock the three hardcoded action targets. A typo in any of these
  // would silently ship — the upvote URL is per-call so we vary it; the
  // Discord invite and feature-request template URLs are constants
  // baked into ComingSoonModal and must match exactly.
  it.each([
    [
      "Upvote on GitHub link uses the per-call upvoteUrl",
      "Upvote MCPs on GitHub",
      DEFAULT_PROPS.upvoteUrl,
    ],
    [
      "Discord link uses the project invite",
      "Join the discussion on Discord",
      "https://discord.gg/KzPuSxgQ98",
    ],
    [
      "Request-a-different-feature link uses the feature_request template",
      "Request a different feature",
      "https://github.com/ric03uec/clawrium/issues/new?template=feature_request.yml",
    ],
  ])("%s", (_desc, accessibleName, expectedHref) => {
    renderModal();
    const link = screen.getByRole("link", { name: accessibleName });
    expect(link).toHaveAttribute("href", expectedHref);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel") ?? "").toContain("noreferrer");
    expect(link.getAttribute("rel") ?? "").toContain("noopener");
  });

  it("upvote link is aria-labeled with the feature name (so SR users know the target)", () => {
    renderModal({ featureName: "Scheduled Jobs" });
    expect(
      screen.getByRole("link", { name: "Upvote Scheduled Jobs on GitHub" }),
    ).toBeInTheDocument();
  });

  it("invokes onClose when the footer Close button fires", () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    const dialog = screen.getByRole("dialog");
    within(dialog)
      .getByRole("button", { name: "Close" })
      .click();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
