import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useTopology() {
  return useQuery({
    queryKey: ["topology"],
    queryFn: api.getTopology,
    refetchInterval: 30_000,
  });
}
