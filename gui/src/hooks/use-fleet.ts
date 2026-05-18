import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useFleet() {
  return useQuery({
    queryKey: ["fleet"],
    queryFn: api.getFleet,
    // No polling here — `/api/fleet` is the cheap optimistic baseline.
    // useFleetHealth() is the live-status poller and merges into this
    // cache; refetching `/api/fleet` would overwrite that merge.
    refetchInterval: false,
  });
}
