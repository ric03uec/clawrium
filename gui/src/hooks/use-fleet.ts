import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useFleet() {
  return useQuery({
    queryKey: ["fleet"],
    queryFn: api.getFleet,
    refetchInterval: 15_000,
  });
}
