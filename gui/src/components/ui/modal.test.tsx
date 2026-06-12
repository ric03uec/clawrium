import { render, screen, fireEvent, act } from "@testing-library/react";
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

  it("invokes onClose exactly once when the close button fires", () => {
    // S3: toHaveBeenCalledTimes(1) (not toHaveBeenCalled) catches a
    // double-invocation regression — easy to introduce if the close
    // listener gets re-attached on every render.
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="t">
        body
      </Modal>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Close dialog/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("invokes onClose when the backdrop is clicked", () => {
    // W1: the onClick handler on <dialog> closes only when the event
    // target is the dialog itself (the backdrop), not when bubbled from
    // an inner child. This test asserts the backdrop branch.
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="t">
        body
      </Modal>,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.click(dialog, { target: dialog, currentTarget: dialog });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not invoke onClose when an inner element is clicked", () => {
    // W1 counterpart: clicks inside the content must not close. The
    // event bubbles to the dialog's onClick, but the target !== dialog
    // guard suppresses the close. Asserts the inner branch.
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="t">
        <span data-testid="content">body</span>
      </Modal>,
    );
    fireEvent.click(screen.getByTestId("content"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("invokes onClose when the dialog fires a native 'close' event", () => {
    // W2: ESC key and any code path that calls native dialog.close()
    // emit the 'close' event. The previous empty-deps effect attached
    // the listener before the dialog mounted, so this path silently
    // broke. Test fires the event and asserts onClose ran.
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="t">
        body
      </Modal>,
    );
    act(() => {
      screen.getByRole("dialog").dispatchEvent(new Event("close"));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("uses the latest onClose closure on subsequent native 'close' events", () => {
    // W2 (latest-closure proof): the onCloseRef pattern means parents
    // can pass a fresh function each render without re-subscribing the
    // listener — but the *latest* function must still be invoked.
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(
      <Modal open onClose={first} title="t">
        body
      </Modal>,
    );
    rerender(
      <Modal open onClose={second} title="t">
        body
      </Modal>,
    );
    act(() => {
      screen.getByRole("dialog").dispatchEvent(new Event("close"));
    });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
