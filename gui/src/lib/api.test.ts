import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  fetchMock.mockReset();
});

describe("api.deleteSkill (ATX #411 B2)", () => {
  it("returns null when the server replies with HTTP 204", async () => {
    // 204 No Content: res.json() would throw SyntaxError.
    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 204, statusText: "No Content" }),
    );
    const result = await api.deleteSkill("foo");
    expect(result).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/skills/local/foo",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("throws on non-2xx delete responses", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("forbidden", { status: 403 }),
    );
    await expect(api.deleteSkill("vetted-name")).rejects.toThrow(
      /API error 403/,
    );
  });
});
