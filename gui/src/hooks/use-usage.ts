import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useUsageSummary(days = 30) {
  return useQuery({
    queryKey: ["usage-summary", days],
    queryFn: () => api.getUsageSummary(days),
  });
}

export function useUsageHistory(days = 7, granularity: "day" | "hour" = "day") {
  return useQuery({
    queryKey: ["usage-history", days, granularity],
    queryFn: () => api.getUsageHistory(days, granularity),
  });
}

export function useUsageByAgent(days = 30) {
  return useQuery({
    queryKey: ["usage-by-agent", days],
    queryFn: () => api.getUsageByAgent(days),
  });
}
