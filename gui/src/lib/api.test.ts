import { describe, expect, it, vi, beforeEach } from "vitest";

import { api } from "@/lib/api";

/**
 * Tests for sendChatMessage SSE streaming logic.
 *
 * We stubGlobal('fetch') so the real function body runs (including
 * ReadableStream + TextDecoder parsing) rather than being replaced by
 * a module-level vi.mock. The component-level tests in chat-tab.test.tsx
 * mock the entire api object; those two test files are complementary.
 */

const mockFetch = vi.fn();

vi.stubGlobal("fetch", mockFetch);

// Helper: build a mock Response with a ReadableStream body
function makeSseResponse(lines: string[], ok = true): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const line of lines) {
        controller.enqueue(encoder.encode(line + "\n"));
      }
      controller.close();
    },
  });
  return new Response(body, {
    status: ok ? 200 : 500,
    statusText: ok ? "OK" : "Internal Server Error",
  });
}

describe("api.sendChatMessage", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("throws on non-OK HTTP status", async () => {
    mockFetch.mockResolvedValue(new Response("server error", { status: 500 }));

    await expect(
      api.sendChatMessage("test-agent", "hi"),
    ).rejects.toThrow("Chat error: 500");
  });

  it("throws when response body is null", async () => {
    // A Response with no body — simulates a network-level failure
    mockFetch.mockResolvedValue(
      new Response(null, { status: 200 }),
    );

    await expect(
      api.sendChatMessage("test-agent", "hi"),
    ).rejects.toThrow("No response body");
  });

  it("throws on SSE error event", async () => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        'data: {"type":"error","message":"upstream fail"}',
        "data: [DONE]",
      ]),
    );

    await expect(
      api.sendChatMessage("test-agent", "hi"),
    ).rejects.toThrow("upstream fail");
  });

  it("resolves with content from SSE stream", async () => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        'data: {"type":"content","text":"hello world"}',
        "data: [DONE]",
      ]),
    );

    const result = await api.sendChatMessage("test-agent", "hi");
    expect(result).toBe("hello world");
  });

  it("passes the AbortSignal through to fetch", async () => {
    const controller = new AbortController();
    mockFetch.mockResolvedValue(
      makeSseResponse([
        'data: {"type":"content","text":"ok"}',
        "data: [DONE]",
      ]),
    );

    await api.sendChatMessage("test-agent", "hi", {
      signal: controller.signal,
    });

    expect(mockFetch).toHaveBeenCalled();
    const fetchOpts = mockFetch.mock.calls[0][1];
    expect(fetchOpts.signal).toBe(controller.signal);
  });

  it("uses default session 'main' when not provided", async () => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        'data: {"type":"content","text":"ok"}',
        "data: [DONE]",
      ]),
    );

    await api.sendChatMessage("test-agent", "hi");

    const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(body.session).toBe("main");
  });

  it("uses provided session override", async () => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        'data: {"type":"content","text":"ok"}',
        "data: [DONE]",
      ]),
    );

    await api.sendChatMessage("test-agent", "hi", {
      session: "custom-thread",
    });

    const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(body.session).toBe("custom-thread");
  });

  it("sanitizes absolute filesystem paths in SSE error messages", async () => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        'data: {"type":"error","message":"config not found at /home/xclm/.config/clawrium/agents/hermes/main"}',
        "data: [DONE]",
      ]),
    );

    await expect(
      api.sendChatMessage("test-agent", "hi"),
    ).rejects.toThrow("[path]");
  });
});
