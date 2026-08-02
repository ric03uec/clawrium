import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import type { ChatInfo } from "@/lib/types";

// jsdom does not implement scrollIntoView; polyfill it
HTMLDivElement.prototype.scrollIntoView = vi.fn();

// Mocked hook state
const chatInfoState: {
  data: ChatInfo | undefined;
  isLoading: boolean;
  error: unknown;
} = { data: undefined, isLoading: false, error: null };

vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn((options: { queryKey: string[] }) => {
    const key = options.queryKey[0];
    if (key === "chat-info") return chatInfoState;
    return { data: undefined, isLoading: false };
  }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    sendChatMessage: vi.fn(),
  },
}));

import { api } from "@/lib/api";

const sendChatMessage = api.sendChatMessage as ReturnType<typeof vi.fn>;

import { ChatTab } from "./chat-tab";

const defaultProps = {
  agentKey: "zeroclaw-localhost:mybox:zeroclaw-agent",
  agentName: "zeroclaw-agent",
};

describe("ChatTab", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    chatInfoState.data = { supported: true, type: "zeroclaw" };
    chatInfoState.isLoading = false;
    chatInfoState.error = null;
    sendChatMessage.mockResolvedValue("Hello from agent!");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the empty-state hint when no messages exist", () => {
    render(<ChatTab {...defaultProps} />);
    expect(
      screen.getByText(/Start a conversation with/i),
    ).toBeInTheDocument();
  });

  it("renders a <textarea> for input, NOT an <input>", () => {
    render(<ChatTab {...defaultProps} />);
    expect(document.querySelector("textarea")).toBeInTheDocument();
    expect(document.querySelector("input")).not.toBeInTheDocument();
  });

  it("the textarea is NOT disabled while sending is true", async () => {
    sendChatMessage.mockReturnValue(new Promise(() => {}));
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    expect(textarea).not.toBeDisabled();

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "test" } });
      fireEvent.keyDown(textarea, { key: "Enter" });
    });

    expect(textarea).not.toBeDisabled();
  });

  it("Enter submits a message", async () => {
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "hello" } });
      fireEvent.keyDown(textarea, { key: "Enter" });
    });

    expect(sendChatMessage).toHaveBeenCalledWith(
      defaultProps.agentKey,
      "hello",
      expect.any(Object),
    );
  });

  it("Shift+Enter does NOT submit", async () => {
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    fireEvent.change(textarea, { target: { value: "line one" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });

    expect(sendChatMessage).not.toHaveBeenCalled();
  });

  it("Enter is a no-op while sending and the draft text survives", async () => {
    sendChatMessage.mockReturnValue(new Promise(() => {}));
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "first" } });
      fireEvent.keyDown(textarea, { key: "Enter" });
    });

    expect(sendChatMessage).toHaveBeenCalledTimes(1);

    fireEvent.change(textarea, { target: { value: "second draft" } });
    await act(async () => {
      fireEvent.keyDown(textarea, { key: "Enter" });
    });

    expect(sendChatMessage).toHaveBeenCalledTimes(1);
    expect(textarea.value).toBe("second draft");
  });

  it("clicking Stop aborts and commits the stopped-marker message", async () => {
    let rejectFn: (v?: any) => void;
    sendChatMessage.mockReturnValue(
      new Promise<never>((_, reject) => { rejectFn = reject; }),
    );
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "do work" } });
      fireEvent.keyDown(textarea, { key: "Enter" });
    });

    // Grab the signal that was passed to the API call
    const signal = sendChatMessage.mock.calls[0][2].signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    const stopBtn = screen.getByRole("button", { name: /Stop/i });
    expect(stopBtn).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(stopBtn);
      rejectFn!(new DOMException("The operation was aborted", "AbortError"));
    });

    // Verify the signal was actually aborted by clicking Stop
    expect(signal.aborted).toBe(true);
    expect(screen.getByText(/Stopped by user/)).toBeInTheDocument();
  });

  it("the Stop button replaces Send only while sending", async () => {
    render(<ChatTab {...defaultProps} />);

    expect(screen.getByRole("button", { name: /Send/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Stop/i }),
    ).not.toBeInTheDocument();

    const textarea = document.querySelector("textarea")!;
    sendChatMessage.mockReturnValue(new Promise(() => {}));
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "hello" } });
      fireEvent.keyDown(textarea, { key: "Enter" });
    });

    expect(screen.getByRole("button", { name: /Stop/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Send/i }),
    ).not.toBeInTheDocument();
  });

  it("shows elapsed time ticking while sending", async () => {
    sendChatMessage.mockReturnValue(new Promise(() => {}));
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "hi" } });
      fireEvent.keyDown(textarea, { key: "Enter" });
    });

    expect(screen.getByText(/Thinking… 0s/)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    expect(screen.getByText(/Thinking… 3s/)).toBeInTheDocument();
  });

  it("displays user and assistant messages after successful round-trip", async () => {
    sendChatMessage.mockResolvedValue("Hello from agent!");
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "user msg" } });
      fireEvent.keyDown(textarea, { key: "Enter" });
    });

    // Flush the microtask queue so the resolved promise settles
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("user msg")).toBeInTheDocument();
    expect(screen.getByText("Hello from agent!")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Stop/i }),
    ).not.toBeInTheDocument();
  });

  it("shows error message on failed request", async () => {
    sendChatMessage.mockRejectedValue(new Error("network error"));
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "fail" } });
      fireEvent.keyDown(textarea, { key: "Enter" });
    });

    // Flush microtask queue so the rejected promise settles
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText(/network error/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Stop/i }),
    ).not.toBeInTheDocument();
  });

  it("Send button is disabled when input is empty", () => {
    render(<ChatTab {...defaultProps} />);
    const sendBtn = screen.getByRole("button", { name: /Send/i });
    expect(sendBtn).toBeDisabled();
  });

  it("Cmd+Enter submits a message", async () => {
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "cmd enter" } });
      fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });
    });

    expect(sendChatMessage).toHaveBeenCalledWith(
      defaultProps.agentKey,
      "cmd enter",
      expect.any(Object),
    );
  });

  it("Ctrl+Enter submits a message", async () => {
    render(<ChatTab {...defaultProps} />);
    const textarea = document.querySelector("textarea")!;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "ctrl enter" } });
      fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    });

    expect(sendChatMessage).toHaveBeenCalledWith(
      defaultProps.agentKey,
      "ctrl enter",
      expect.any(Object),
    );
  });
});
