import { describe, expect, it } from "vitest";

import { buildHostColorMap, getHostColor } from "./host-colors";

describe("buildHostColorMap", () => {
  it("returns an empty map for no hosts", () => {
    const map = buildHostColorMap([]);
    expect(map.size).toBe(0);
  });

  it("assigns the same color to duplicate hostnames", () => {
    const map = buildHostColorMap(["wolf-i", "wolf-i", "wolf-i"]);
    expect(map.size).toBe(1);
    expect(map.get("wolf-i")).toBeDefined();
  });

  it("assigns distinct colors to two distinct hosts", () => {
    const map = buildHostColorMap(["wolf-i", "kevin"]);
    expect(map.get("wolf-i")).not.toBe(map.get("kevin"));
  });

  it("wraps the palette modulo when there are more hosts than colors", () => {
    const hosts = Array.from({ length: 9 }, (_, i) => `host-${i}`);
    const map = buildHostColorMap(hosts);
    // The 9th host should reuse the color assigned to the first host.
    expect(map.get("host-0")).toBe(map.get("host-8"));
  });
});

describe("getHostColor", () => {
  it("returns the assigned color when the hostname is in the map", () => {
    const map = buildHostColorMap(["wolf-i"]);
    expect(getHostColor(map, "wolf-i")).toBe(map.get("wolf-i"));
  });

  it("returns the first palette entry as a fallback for unknown hostnames", () => {
    const map = buildHostColorMap(["wolf-i"]);
    const fallback = getHostColor(map, "unknown-host");
    expect(fallback).toBeDefined();
    // The fallback for an unknown host should be deterministic.
    expect(getHostColor(map, "another-unknown")).toBe(fallback);
  });
});
