import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { Modal } from "./modal";

// jsdom does not implement HTMLDialogElement.showModal / close. Stub
// them so the Modal's open/close effects can run without throwing.
// This shim is intentionally minimal: it flips an "open" attribute so
// querying by role="dialog" works the same way browsers expose it via
// the dialog tag. ATX-3 B1 wants real-Modal coverage; without these
// stubs jsdom raises "Not implemented: HTMLDialogElement.prototype.showModal".
beforeEach(() => {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    };
  }
});

describe("Modal a11y", () => {
  it("renders the <dialog> with aria-modal and aria-labelledby wired to the heading", () => {
    // ATX-3 B1: every other test mocks Modal as a <div>; the real
    // dialog/aria wiring is dark without this test. A regression that
    // dropped aria-modal or unlinked aria-labelledby would otherwise
    // pass every existing suite.
    render(
      <Modal open onClose={vi.fn()} title="Install skill on tdd-hermes">
        body
      </Modal>,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog.tagName).toBe("DIALOG");
    expect(dialog).toHaveAttribute("aria-modal", "true");

    // aria-labelledby must point at the rendered <h2>, so a SR reads
    // the title when the dialog opens.
    const labelId = dialog.getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    const heading = document.getElementById(labelId as string);
    expect(heading).not.toBeNull();
    expect(heading).toHaveTextContent("Install skill on tdd-hermes");
  });

  it("the ✕ button has an accessible name (not the raw glyph)", () => {
    // ATX-1 W5 (acknowledged in Review 3): the close button is the
    // only way out via mouse — must be readable by a screen reader.
    render(
      <Modal open onClose={vi.fn()} title="t">
        body
      </Modal>,
    );
    expect(
      screen.getByRole("button", { name: /Close dialog/i }),
    ).toBeInTheDocument();
  });

  it("invokes onClose when the close button fires", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="t">
        body
      </Modal>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Close dialog/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
