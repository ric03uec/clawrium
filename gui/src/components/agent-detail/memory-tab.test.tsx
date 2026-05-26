import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import type { MemoryInfo, MemoryFileContent } from "@/lib/types";

// Mocked hook state — each test resets the slots in beforeEach.
const memoryInfoState: {
  data: MemoryInfo | undefined;
  isLoading: boolean;
  error: unknown;
} = { data: undefined, isLoading: false, error: null };

const fileContentState: {
  data: MemoryFileContent | undefined;
  isLoading: boolean;
  error: unknown;
} = { data: undefined, isLoading: false, error: null };

const saveMutation = {
  mutate: vi.fn(),
  isPending: false,
};

const queryClient = {
  invalidateQueries: vi.fn(),
};

vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn((options: { queryKey: string[] }) => {
    const key = options.queryKey[0];
    if (key === "memory") {
      return memoryInfoState;
    }
    if (key === "memory-file") {
      return fileContentState;
    }
    return { data: undefined, isLoading: false };
  }),
  useMutation: vi.fn(() => saveMutation),
  useQueryClient: vi.fn(() => queryClient),
}));

// Mock clipboard API
const clipboardWriteText = vi.fn();
Object.assign(navigator, {
  clipboard: {
    writeText: clipboardWriteText,
  },
});

import { MemoryTab } from "./memory-tab";

function makeMemoryInfo(overrides: Partial<MemoryInfo> = {}): MemoryInfo {
  return {
    supported: true,
    workspace_path: "/home/user/.config/hermes/test-agent",
    files: [
      {
        name: "MEMORY.md",
        exists: true,
        size_bytes: 1024,
        relative_path: "MEMORY.md",
      },
      {
        name: "SKILLS.md",
        exists: true,
        size_bytes: 512,
        relative_path: "skills/SKILLS.md",
      },
    ],
    ...overrides,
  };
}

function makeFileContent(
  content: string = "Test memory content",
): MemoryFileContent {
  return {
    filename: "MEMORY.md",
    content,
  };
}

describe("MemoryTab", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    memoryInfoState.data = undefined;
    memoryInfoState.isLoading = false;
    memoryInfoState.error = null;
    fileContentState.data = undefined;
    fileContentState.isLoading = false;
    saveMutation.mutate = vi.fn();
    saveMutation.isPending = false;
    clipboardWriteText.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows copy button when a file is selected", () => {
    memoryInfoState.data = makeMemoryInfo();
    fileContentState.data = makeFileContent();
    render(<MemoryTab agentKey="test-agent" />);
    // Click on a file to select it
    fireEvent.click(screen.getByRole("button", { name: "MEMORY.md" }));
    expect(
      screen.getByRole("button", { name: /copy/i }),
    ).toBeInTheDocument();
  });

  it("clicking Copy calls navigator.clipboard.writeText with file content", async () => {
    memoryInfoState.data = makeMemoryInfo();
    fileContentState.data = makeFileContent("My memory content");
    clipboardWriteText.mockResolvedValueOnce(undefined);
    render(<MemoryTab agentKey="test-agent" />);
    fireEvent.click(screen.getByRole("button", { name: "MEMORY.md" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    });
    expect(clipboardWriteText).toHaveBeenCalledWith("My memory content");
  });

  it("button label changes to Copied after successful copy", async () => {
    memoryInfoState.data = makeMemoryInfo();
    fileContentState.data = makeFileContent();
    clipboardWriteText.mockResolvedValueOnce(undefined);
    render(<MemoryTab agentKey="test-agent" />);
    fireEvent.click(screen.getByRole("button", { name: "MEMORY.md" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy/i }));
      // Flush pending promises
      await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: /copied/i })).toBeInTheDocument();
  });

  it("button label reverts to Copy after timeout", async () => {
    memoryInfoState.data = makeMemoryInfo();
    fileContentState.data = makeFileContent();
    clipboardWriteText.mockResolvedValueOnce(undefined);
    render(<MemoryTab agentKey="test-agent" />);
    fireEvent.click(screen.getByRole("button", { name: "MEMORY.md" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy/i }));
      await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: /copied/i })).toBeInTheDocument();
    // Advance timers by 1500ms
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    expect(screen.getByRole("button", { name: /^copy$/i })).toBeInTheDocument();
  });

  it("copy button copies editContent when in edit mode", async () => {
    memoryInfoState.data = makeMemoryInfo();
    fileContentState.data = makeFileContent("Original content");
    clipboardWriteText.mockResolvedValueOnce(undefined);
    render(<MemoryTab agentKey="test-agent" />);
    fireEvent.click(screen.getByRole("button", { name: "MEMORY.md" }));
    // Enter edit mode
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    // Edit the content
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "Edited content" } });
    // Copy should use edited content
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    });
    expect(clipboardWriteText).toHaveBeenCalledWith("Edited content");
  });

  it("copy button is disabled when content is empty", () => {
    memoryInfoState.data = makeMemoryInfo();
    fileContentState.data = makeFileContent("");
    render(<MemoryTab agentKey="test-agent" />);
    fireEvent.click(screen.getByRole("button", { name: "MEMORY.md" }));
    expect(screen.getByRole("button", { name: /copy/i })).toBeDisabled();
  });

  it("clipboard API errors are caught gracefully", async () => {
    memoryInfoState.data = makeMemoryInfo();
    fileContentState.data = makeFileContent();
    clipboardWriteText.mockRejectedValueOnce(new Error("Clipboard not allowed"));
    render(<MemoryTab agentKey="test-agent" />);
    fireEvent.click(screen.getByRole("button", { name: "MEMORY.md" }));
    // Should not throw
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy/i }));
      await Promise.resolve();
    });
    // Button should still be present and say Copy (not Copied)
    expect(screen.getByRole("button", { name: /^copy$/i })).toBeInTheDocument();
  });
});
