import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => api.getSettings(),
  });
}

export function useVersion() {
  return useQuery({
    queryKey: ["version"],
    queryFn: () => api.getVersion(),
  });
}

export function useClearUsage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.clearUsage(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["usage-summary"] });
      queryClient.invalidateQueries({ queryKey: ["usage-history"] });
      queryClient.invalidateQueries({ queryKey: ["usage-by-agent"] });
    },
  });
}
