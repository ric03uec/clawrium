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

function makeChunkedSseResponse(payload: string, splitAt: number[]): Response {
  const bytes = new TextEncoder().encode(payload);
  const body = new ReadableStream({
    start(controller) {
      let start = 0;
      for (const end of splitAt) {
        controller.enqueue(bytes.slice(start, end));
        start = end;
      }
      controller.enqueue(bytes.slice(start));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
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

  it("buffers an SSE line and UTF-8 code point split across chunks", async () => {
    const payload = 'data: {"type":"content","text":"hello 世界"}\n' +
      "data: [DONE]";
    const encodedPrefix = new TextEncoder().encode(
      'data: {"type":"content","text":"hello 世',
    ).length;
    mockFetch.mockResolvedValue(
      makeChunkedSseResponse(payload, [8, encodedPrefix - 1, encodedPrefix]),
    );

    await expect(api.sendChatMessage("test-agent", "hi")).resolves.toBe(
      "hello 世界",
    );
  });

  it("handles CRLF, empty streams, and last-content-wins semantics", async () => {
    mockFetch.mockResolvedValue(
      makeChunkedSseResponse(
        'data: {"type":"content","text":"first"}\r\n' +
          'data: {"type":"content","text":"second"}\r\n' +
          "data: [DONE]\r\n",
        [5, 31],
      ),
    );
    await expect(api.sendChatMessage("test-agent", "hi")).resolves.toBe(
      "second",
    );

    mockFetch.mockResolvedValue(makeSseResponse(["data: [DONE]"]));
    await expect(api.sendChatMessage("test-agent", "hi")).resolves.toBe("");
  });

  it("ignores non-string content, preserves whitespace, and strips unsafe formatting", async () => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        'data: {"type":"content","text":42}',
        `data: ${JSON.stringify({ type: "content", text: "line one\nline two\t\u202etext" })}`,
        "data: [DONE]",
      ]),
    );

    await expect(api.sendChatMessage("test-agent", "hi")).resolves.toBe(
      "line one\nline two\t text",
    );
  });

  it("skips malformed SSE JSON and continues parsing", async () => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        "data: {broken json}",
        'data: {"type":"content","text":"ok"}',
        "data: [DONE]",
      ]),
    );

    await expect(api.sendChatMessage("test-agent", "hi")).resolves.toBe("ok");
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

    expect(mockFetch).toHaveBeenCalledOnce();
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

  it.each([
    "/home/xclm/.config/clawrium/agents/hermes/main",
    "/Users/alice/.config/clawrium",
    "/etc/clawrium/config.toml",
    "/var/lib/clawrium/state.db",
    "/opt/clawrium/bin/agent",
  ])("sanitizes absolute filesystem path %s", async (path) => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        `data: ${JSON.stringify({ type: "error", message: `config not found at ${path}` })}`,
        "data: [DONE]",
      ]),
    );

    const error = await api.sendChatMessage("test-agent", "hi").catch((e) => e);
    expect(error.message).toContain("[path]");
    expect(error.message).not.toContain(path);
  });

  it.each([
    ["token=abc123\u202esecret", "token=*** secret"],
    ["Bearer eyJhbGc.secret", "Bearer ***"],
  ])("redacts credentials and terminal controls in %s", async (message, expected) => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        `data: ${JSON.stringify({ type: "error", message })}`,
        "data: [DONE]",
      ]),
    );

    await expect(api.sendChatMessage("test-agent", "hi")).rejects.toThrow(
      expected,
    );
  });

  it("uses a safe fallback for non-string SSE errors", async () => {
    mockFetch.mockResolvedValue(
      makeSseResponse([
        'data: {"type":"error","message":42}',
        "data: [DONE]",
      ]),
    );

    await expect(api.sendChatMessage("test-agent", "hi")).rejects.toThrow(
      "Chat failed",
    );
  });
});
