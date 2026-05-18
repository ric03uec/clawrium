/**
 * Host color palette: assigns a consistent color to each unique host
 * so agents from the same host share a visual grouping.
 */

/** Ordered palette - visually distinct, accessible on white bg */
const HOST_COLORS = [
  "#0D9488", // teal-600
  "#0EA5E9", // sky-500
  "#8B5CF6", // violet-500
  "#F59E0B", // amber-500
  "#EC4899", // pink-500
  "#10B981", // emerald-500
  "#6366F1", // indigo-500
  "#EF4444", // red-500
] as const;

export type HostColorMap = Map<string, string>;

/**
 * Build a deterministic hostname → color mapping.
 * Colors are assigned in encounter order (stable across re-renders
 * as long as the hosts array order doesn't change).
 */
export function buildHostColorMap(hostnames: string[]): HostColorMap {
  const map = new Map<string, string>();
  const unique = [...new Set(hostnames)];
  unique.forEach((hostname, idx) => {
    map.set(hostname, HOST_COLORS[idx % HOST_COLORS.length]);
  });
  return map;
}

/**
 * Get color for a given hostname from the map, with fallback.
 */
export function getHostColor(map: HostColorMap, hostname: string): string {
  return map.get(hostname) ?? HOST_COLORS[0];
}
